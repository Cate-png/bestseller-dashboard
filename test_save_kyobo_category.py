"""분야별(categories.py의 CATEGORIES 14개 분야) TOP20 베스트셀러 수집 -> Supabase 저장.

test_save_kyobo.py와 동일하게 내부 JSON API 기반으로 전환했습니다(기존
HTML 스크래핑 + 상세페이지 순회 방식 폐기). test_save_kyobo.py의
fetch_best_seller_page/item_to_book을 그대로 import해서 재사용하고,
test_save_kyobo.py 자체는 전혀 수정하지 않습니다.

목록 페이지: 교보문고 "온라인 주간 베스트 | 국내도서 | {분야}" 페이지
(https://store.kyobobook.co.kr/bestseller/online/weekly/domestic/{코드})가
실제로는 다음 API로 데이터를 채웁니다(GitHub Actions에서 실제 네트워크
응답으로 확인함):
  https://store.kyobobook.co.kr/api/gw/best/best-seller/online
    ?page=1&per=20&period=002&dsplDvsnCode=001&dsplTrgtDvsnCode=004
    &saleCmdtClstCode={분야코드}
saleCmdtClstCode 값은 기존 categories.py의 kyobo_domestic_code와 동일한
값(01=소설, 03=에세이/시, 05=인문, 13=경제경영, 15=자기계발, 19=역사)이라
categories.py의 카테고리 코드를 그대로 재사용합니다. 응답 항목 구조
(prstRnkn/frmrRnkn/cmdtCode/cmdtName/chrcName/pbcmName 등)도 종합(total)
API와 동일한 것을 확인했습니다.

기존 스크립트와의 차이:
- 분야마다 TOP20까지만 수집합니다 (목록 페이지 1페이지만 조회, per=20
  전부 사용).
- collection_runs는 "이번 분야별 수집 전체"를 대표하는 행 1개만 남기고,
  rankings에는 분야별로 category 값을 다르게 저장합니다.
- 분야 하나가 실패해도 나머지 분야 수집은 계속 진행합니다.
- rank_change는 API의 frmrRnkn(이전 순위)과 prstRnkn(현재 순위)을 직접
  비교해서 계산합니다(test_save_kyobo.py의 item_to_book과 동일한 규칙).
  더 이상 categories.py의 get_previous_category_ranks(직전 Supabase
  스냅샷 비교)를 쓰지 않습니다 - 이 함수는 알라딘 분야별 수집
  (test_save_aladin_category.py)이 계속 쓰므로 categories.py에서
  제거하지 않았습니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY (기존과 동일, 추가 Secret 없음)
"""

import os
import sys
from datetime import datetime, timezone

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

try:
    from supabase import create_client
except ImportError:
    print("오류: supabase 라이브러리가 설치되어 있지 않습니다. (pip install supabase)")
    sys.exit(1)

from categories import CATEGORIES, TOP_N
from supabase_retry import execute_with_retry
from test_save_kyobo import USER_AGENT, fetch_best_seller_page, item_to_book

BOOKSTORE = "교보문고"
LIST_URL_BASE = "https://store.kyobobook.co.kr/bestseller/online/weekly/domestic"


def load_top_n_list(page, domestic_code, n=TOP_N):
    list_url = f"{LIST_URL_BASE}/{domestic_code}"
    print(f"   목록 페이지 로딩 중... ({list_url})")
    items = fetch_best_seller_page(page, list_url)
    books = [item_to_book(item) for item in items if item.get("prstRnkn")]
    books.sort(key=lambda b: b["rank"])
    return books[:n]


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)
    collected_at = datetime.now(timezone.utc).isoformat()

    all_books = []
    category_errors = {}

    for cat in CATEGORIES:
        category = cat["category"]
        print(f"\n=== 교보문고 · {category} TOP{TOP_N} 수집 시작 ===")
        try:
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as e:
                    raise RuntimeError(
                        f"브라우저 실행 실패: {e} "
                        "('playwright install chromium' 실행 여부 확인 필요)"
                    )
                page = browser.new_page(user_agent=USER_AGENT)
                books = load_top_n_list(page, cat["kyobo_domestic_code"], TOP_N)
                browser.close()

            if not books:
                raise RuntimeError("목록에서 도서를 하나도 추출하지 못했습니다.")

            for book in books:
                book["category"] = category

            all_books.extend(books)
            print(f"   -> {category} {len(books)}권 수집 성공")
        except Exception as e:
            category_errors[category] = str(e)
            print(f"   -> {category} 수집 실패: {e}")

    status = "success" if all_books else "failed"
    error_message = "; ".join(f"{c}: {m}" for c, m in category_errors.items()) or None

    run_insert = execute_with_retry(
        client.table("collection_runs")
        .insert({
            "bookstore": BOOKSTORE,
            "status": status,
            "error_message": error_message,
            "item_count": len(all_books),
        })
    )
    run_id = run_insert.data[0]["id"]
    print(f"\ncollection_runs 기록 완료. run_id={run_id}, status={status}, 총 {len(all_books)}권")

    if not all_books:
        print("저장할 도서 데이터가 없어 books/rankings 저장은 건너뜁니다.")
        sys.exit(1)

    books_payload = []
    seen_isbn = set()
    for book in all_books:
        isbn13 = book.get("isbn13")
        if not isbn13 or isbn13 in seen_isbn:
            continue
        seen_isbn.add(isbn13)
        books_payload.append({
            "isbn13": isbn13,
            "title": book["title"],
            "author": book["author"],
            "publisher": book["publisher"],
            "updated_at": collected_at,
        })

    books_saved = 0
    if books_payload:
        result = execute_with_retry(
            client.table("books").upsert(books_payload, on_conflict="isbn13")
        )
        books_saved = len(result.data)
    print(f"books 테이블 upsert 완료: {books_saved}건")

    rankings_payload = [
        {
            "run_id": run_id,
            "collected_at": collected_at,
            "bookstore": BOOKSTORE,
            "category": book["category"],
            "rank": book["rank"],
            "title": book["title"],
            "author": book["author"],
            "publisher": book["publisher"],
            "isbn13": book.get("isbn13"),
            "url": book["url"],
            "match_status": book["match_status"],
            "rank_change": book["rank_change"],
        }
        for book in all_books
    ]
    rankings_result = execute_with_retry(
        client.table("rankings").insert(rankings_payload)
    )
    print(f"rankings 테이블 저장 완료: {len(rankings_result.data)}건")

    if category_errors:
        print("\n일부 분야 수집 실패:")
        for c, m in category_errors.items():
            print(f"  - {c}: {m}")

    print("\n" + "=" * 80)
    print("분야별(교보문고) 수집 결과 요약")
    print("=" * 80)
    for cat in CATEGORIES:
        cat_books = [b for b in all_books if b["category"] == cat["category"]]
        print(f"[{cat['category']}] {len(cat_books)}권")
        for b in sorted(cat_books, key=lambda x: x["rank"]):
            print(f"   {b['rank']}위 | {b['title']} | {b['author']} | {b['publisher']}")

    if category_errors:
        sys.exit(0 if all_books else 1)


if __name__ == "__main__":
    main()

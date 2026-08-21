"""분야별(소설/에세이시/인문/경제경영/자기계발/역사) TOP10 베스트셀러 수집 -> Supabase 저장.

기존 종합 TOP100 수집 스크립트(test_save_kyobo.py)에서 실제로 검증된 로직
(상세 페이지 파싱 함수 fetch_detail, 목록 페이지의 img selector 등)을 그대로
import해서 재사용합니다. test_save_kyobo.py 자체는 전혀 수정하지 않고, 이
스크립트를 실행해도 그쪽 로직에는 아무 영향이 없습니다.

목록 페이지: 교보문고 "온라인 주간 베스트 | 국내도서 | {분야}" 페이지
(https://store.kyobobook.co.kr/bestseller/online/weekly/domestic/{코드})를
사용합니다. 분야별 코드는 categories.py에 정리되어 있습니다.

기존 스크립트와의 차이:
- 분야마다 TOP10까지만 수집합니다 (목록 페이지 1페이지만 조회).
- collection_runs는 "이번 분야별 수집 전체"를 대표하는 행 1개만 남기고,
  rankings에는 분야별로 category 값을 다르게 저장합니다.
- 분야 하나가 실패해도 나머지 분야 수집은 계속 진행합니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY (기존과 동일, 추가 Secret 없음)

상세 페이지 조회는 test_save_kyobo.py와 동일하게 concurrency_utils를 통해
DETAIL_CONCURRENCY(기본 4)개씩 동시 처리합니다.
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

from categories import CATEGORIES, TOP_N, get_previous_category_ranks
from concurrency_utils import enrich_details_concurrently
from test_save_kyobo import fetch_detail, GET_HREF_JS, IMG_SELECTOR

BOOKSTORE = "교보문고"
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def load_top_n_list(page, domestic_code, n=TOP_N):
    list_url = f"https://store.kyobobook.co.kr/bestseller/online/weekly/domestic/{domestic_code}"
    print(f"   목록 페이지 로딩 중... ({list_url})")
    page.goto(list_url, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    imgs = page.locator(IMG_SELECTOR)
    count = imgs.count()
    books = []
    seen_urls = set()
    rank = 1
    for i in range(count):
        if rank > n:
            break
        img = imgs.nth(i)
        title = img.get_attribute("alt")
        href = img.evaluate(GET_HREF_JS)
        if not href or href in seen_urls or not title:
            continue
        seen_urls.add(href)
        full_url = href if href.startswith("http") else "https://product.kyobobook.co.kr" + href
        books.append({"rank": rank, "title": title.strip(), "url": full_url})
        rank += 1

    return books


def _fetch_one_detail(page, book):
    try:
        detail = fetch_detail(page, book["url"])
    except Exception as e:
        print(f"      -> 상세 페이지 조회 실패, 제목/URL만 저장합니다: {e}")
        detail = {"author": "", "publisher": "", "isbn13": None}

    book["author"] = detail["author"]
    book["publisher"] = detail["publisher"]
    book["isbn13"] = detail["isbn13"]


def enrich_with_details(books):
    return enrich_details_concurrently(
        books,
        fetch_one=_fetch_one_detail,
        user_agent=USER_AGENT,
        concurrency=DETAIL_CONCURRENCY,
        request_delay=DETAIL_REQUEST_DELAY,
    )


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
            prev_ranks = get_previous_category_ranks(client, BOOKSTORE, category)

            # 목록 페이지는 분야마다 짧게 브라우저를 열었다 닫습니다(상세 페이지
            # 동시 조회용 워커 스레드들이 각자 별도의 Playwright 인스턴스를 쓰기
            # 때문에, 목록용 인스턴스와 시간상 겹치지 않게 해서 더 단순하고
            # 안전하게 구성했습니다).
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
            books = enrich_with_details(books)

            for book in books:
                isbn13 = book.get("isbn13")
                if isbn13 and isbn13 in prev_ranks:
                    book["rank_change"] = prev_ranks[isbn13] - book["rank"]
                else:
                    book["rank_change"] = None
                book["match_status"] = "matched" if isbn13 else "no_isbn"
                book["category"] = category

            all_books.extend(books)
            print(f"   -> {category} {len(books)}권 수집 성공")
        except Exception as e:
            category_errors[category] = str(e)
            print(f"   -> {category} 수집 실패: {e}")

    status = "success" if all_books else "failed"
    error_message = "; ".join(f"{c}: {m}" for c, m in category_errors.items()) or None

    run_insert = (
        client.table("collection_runs")
        .insert({
            "bookstore": BOOKSTORE,
            "status": status,
            "error_message": error_message,
            "item_count": len(all_books),
        })
        .execute()
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
        result = client.table("books").upsert(books_payload, on_conflict="isbn13").execute()
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
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
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

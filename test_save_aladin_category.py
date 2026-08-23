"""분야별(categories.py의 CATEGORIES 14개 분야) TOP20 베스트셀러 수집 -> Supabase 저장.

기존 종합 TOP100 수집 스크립트(test_save_aladin.py)에서 실제로 검증된 목록/상세
페이지 파싱 로직(parse_list, parse_detail)과 요청 함수(goto_with_retry)를 그대로
import해서 재사용합니다. test_save_aladin.py 자체는 전혀 수정하지 않고, 목록
페이지 요청 시 CID 파라미터만 분야별로 바꿔서 호출합니다.

분야별 CID는 categories.py에 정리되어 있습니다.

페이지 요청 방식(requests -> Playwright)에 대해: test_save_aladin.py와 동일한
이유로 requests 대신 Playwright(Chromium)로 페이지를 엽니다. GitHub Actions에서
requests로 알라딘에 접근하면 "403 Client Error: Forbidden"이 발생했는데, 같은
워크플로에서 Playwright로 접근하는 교보문고는 문제없이 동작했기 때문입니다.
(자세한 내용은 test_save_aladin.py의 goto_with_retry 주석 참고)

기존 스크립트와의 차이:
- 분야마다 TOP20까지만 수집합니다 (기존은 TOP100을 위해 2페이지를 조회했지만,
  여기서는 1페이지 조회 결과에서 앞 20권만 사용합니다 - 1페이지가 최대
  50건을 주므로 페이지네이션 없이 충분합니다).
- collection_runs는 "이번 분야별 수집 전체"를 대표하는 행 1개만 남기고,
  rankings에는 분야별로 category 값을 다르게 저장합니다.
- 분야 하나가 실패해도 나머지 분야 수집은 계속 진행합니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY (기존과 동일, 추가 Secret 없음)

상세 페이지 조회는 test_save_aladin.py와 동일하게 concurrency_utils를 통해
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
from test_save_aladin import (
    CONTEXT_KWARGS,
    HEADERS,
    goto_with_retry,
    parse_list,
    parse_detail,
)

BOOKSTORE = "알라딘"
LIST_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx"
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4


def fetch_category_list_page(page, cid: str) -> str:
    params = {
        "BestType": "Bestseller",
        "BranchType": "1",  # 국내도서
        "CID": cid,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    return goto_with_retry(page, url)


def collect_top_n(page, cid: str, n: int):
    html = fetch_category_list_page(page, cid)
    books = parse_list(html, start_rank=1)
    if not books:
        raise RuntimeError("목록 페이지에서 도서를 하나도 추출하지 못했습니다.")
    return books[:n]


def _fetch_one_detail(page, book):
    try:
        html = goto_with_retry(page, book["url"])
        detail = parse_detail(html)
    except Exception as e:
        print(f"      -> 상세 페이지 조회 실패, 제목/URL만 저장합니다: {e}")
        detail = {"author": "", "publisher": "", "isbn13": ""}

    book["author"] = detail["author"]
    book["publisher"] = detail["publisher"]
    book["isbn13"] = detail["isbn13"] or None


def enrich_with_details(books):
    return enrich_details_concurrently(
        books,
        fetch_one=_fetch_one_detail,
        user_agent=HEADERS["User-Agent"],
        concurrency=DETAIL_CONCURRENCY,
        request_delay=DETAIL_REQUEST_DELAY,
        context_kwargs=CONTEXT_KWARGS,
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
        print(f"\n=== 알라딘 · {category} TOP{TOP_N} 수집 시작 (CID={cat['aladin_cid']}) ===")
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
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"], **CONTEXT_KWARGS
                )
                books = collect_top_n(page, cat["aladin_cid"], TOP_N)
                browser.close()

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
        result = (
            client.table("books")
            .upsert(books_payload, on_conflict="isbn13")
            .execute()
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
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
    print(f"rankings 테이블 저장 완료: {len(rankings_result.data)}건")

    if category_errors:
        print("\n일부 분야 수집 실패:")
        for c, m in category_errors.items():
            print(f"  - {c}: {m}")

    print("\n" + "=" * 80)
    print("분야별(알라딘) 수집 결과 요약")
    print("=" * 80)
    for cat in CATEGORIES:
        cat_books = [b for b in all_books if b["category"] == cat["category"]]
        print(f"[{cat['category']}] {len(cat_books)}권")
        for b in sorted(cat_books, key=lambda x: x["rank"]):
            print(f"   {b['rank']}위 | {b['title']} | {b['author']} | {b['publisher']}")


if __name__ == "__main__":
    main()

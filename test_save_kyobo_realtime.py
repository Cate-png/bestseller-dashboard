"""교보문고 "실시간 베스트셀러" 수집 -> Supabase realtime_rankings 저장.

기존 종합 주간 스크립트(test_save_kyobo.py)에서 실제로 검증된 상세 페이지
파싱 로직(fetch_detail, GET_HREF_JS, ISBN13_PATTERN, IMG_SELECTOR)을 그대로
import해서 재사용합니다. test_save_kyobo.py 자체는 전혀 수정하지 않습니다.

목록 페이지: https://store.kyobobook.co.kr/bestseller/realtime
- 교보문고 사이트 자체 설명상 1시간마다 갱신되는 실시간 베스트셀러이며,
  기존에 쓰던 /bestseller/total/weekly(주간)와는 완전히 다른 URL입니다.
- diagnose_realtime.py로 GitHub Actions에서 실제로 확인한 내용:
  * 이 페이지는 기본 렌더링으로 TOP20까지만 노출됩니다. 추가 페이지네이션
    파라미터(?page=N 등)가 이 URL에서도 동작하는지는 확인하지 못했으므로,
    짐작으로 추가하지 않고 확인된 범위(TOP20)만 수집합니다.
  * 도서 상세 selector(a[href*='product.kyobobook.co.kr/detail/'] img)가
    매칭한 20건 전부 실제 도서였고, 전자책/기프트/교보only 상품이 섞여
    들어오지 않는 것을 확인했습니다. 이 selector 자체가 사실상 도서 전용
    필터 역할을 하므로 별도 필터링 로직 없이 그대로 재사용합니다.

기존 weekly/분야별 시스템과의 분리:
- rankings / collection_runs / books 테이블에는 전혀 쓰지 않고,
  realtime_rankings / realtime_collection_runs 테이블에만 저장합니다.
  (books 테이블도 weekly와 공유하지 않기 위해 일부러 쓰지 않고, 제목/작가/
  출판사를 realtime_rankings 행에 그대로 함께 저장합니다.)
- test_save_kyobo.py, test_save_kyobo_category.py, categories.py,
  collect.yml(매일 06시 정기 수집)은 전혀 건드리지 않습니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
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

from concurrency_utils import enrich_details_concurrently
from test_save_kyobo import fetch_detail, GET_HREF_JS, IMG_SELECTOR

BOOKSTORE = "교보문고"
LIST_URL = "https://store.kyobobook.co.kr/bestseller/realtime"
TARGET_COUNT = 20  # diagnose_realtime.py로 확인된 기본 렌더링 범위
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def load_realtime_list(page):
    page.goto(LIST_URL, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    imgs = page.locator(IMG_SELECTOR)
    count = imgs.count()
    books = []
    seen_urls = set()
    rank = 1
    for i in range(count):
        if rank > TARGET_COUNT:
            break
        img = imgs.nth(i)
        title = img.get_attribute("alt")
        href = img.evaluate(GET_HREF_JS)
        if not href or href in seen_urls or not title:
            continue
        seen_urls.add(href)
        full_url = (
            href if href.startswith("http") else "https://product.kyobobook.co.kr" + href
        )
        books.append({"rank": rank, "title": title.strip(), "url": full_url})
        rank += 1

    return books


def _fetch_one_detail(page, book):
    try:
        detail = fetch_detail(page, book["url"])
    except Exception as e:
        print(f"   -> 상세 페이지 조회 실패, 이 도서는 제목/URL만 저장합니다: {e}")
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


def get_previous_realtime_ranks(client):
    """realtime_rankings에서 이 서점의 가장 최근 실시간 스냅샷 isbn13 -> rank
    매핑을 가져옵니다. rankings(주간)과는 완전히 다른 테이블이라 서로 섞일
    여지가 없습니다."""
    latest = (
        client.table("realtime_rankings")
        .select("collected_at")
        .eq("bookstore", BOOKSTORE)
        .order("collected_at", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return {}

    latest_collected_at = latest.data[0]["collected_at"]
    prev = (
        client.table("realtime_rankings")
        .select("isbn13, rank")
        .eq("bookstore", BOOKSTORE)
        .eq("collected_at", latest_collected_at)
        .execute()
    )
    return {row["isbn13"]: row["rank"] for row in prev.data if row["isbn13"]}


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("직전 교보문고 실시간 수집 결과 조회 중 (순위 변동 계산용)...")
    prev_ranks = get_previous_realtime_ranks(client)
    print(f"직전 스냅샷 도서 수: {len(prev_ranks)}권\n")

    collected_at = datetime.now(timezone.utc).isoformat()
    error_message = None
    books = []

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
            books = load_realtime_list(page)
            browser.close()

        if not books:
            raise RuntimeError("실시간 목록에서 도서를 하나도 추출하지 못했습니다.")

        print(
            f"\n목록 수집 성공: {len(books)}권. "
            f"상세 페이지를 동시성={DETAIL_CONCURRENCY}로 조회합니다.\n"
        )
        books = enrich_with_details(books)
    except Exception as e:
        error_message = str(e)
        print(f"\n교보문고 실시간 수집이 완전히 실패했습니다: {error_message}")

    for book in books:
        isbn13 = book.get("isbn13")
        if isbn13 and isbn13 in prev_ranks:
            book["rank_change"] = prev_ranks[isbn13] - book["rank"]
        else:
            book["rank_change"] = None
        book["match_status"] = "matched" if isbn13 else "no_isbn"

    status = "success" if books else "failed"

    run_insert = (
        client.table("realtime_collection_runs")
        .insert({
            "bookstore": BOOKSTORE,
            "status": status,
            "error_message": error_message,
            "item_count": len(books),
        })
        .execute()
    )
    run_id = run_insert.data[0]["id"]
    print(f"realtime_collection_runs 기록 완료. run_id={run_id}, status={status}")

    if not books:
        print("저장할 도서 데이터가 없어 realtime_rankings 저장은 건너뜁니다.")
        sys.exit(1)

    rankings_payload = [
        {
            "run_id": run_id,
            "collected_at": collected_at,
            "bookstore": BOOKSTORE,
            "rank": book["rank"],
            "title": book["title"],
            "author": book["author"],
            "publisher": book["publisher"],
            "isbn13": book.get("isbn13"),
            "url": book["url"],
            "match_status": book["match_status"],
            "rank_change": book["rank_change"],
        }
        for book in books
    ]
    rankings_result = client.table("realtime_rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"realtime_rankings 저장 완료: {rankings_saved}건")

    print("\n" + "=" * 80)
    print(f"교보문고 실시간 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"수집 권수: {len(books)}")
    print(f"realtime_rankings 저장 권수: {rankings_saved}")
    print("=" * 80)
    print("실시간 TOP (순위 | 도서명 | 저자 | 출판사 | ISBN13 | 등락)")
    print("=" * 80)
    for book in sorted(books, key=lambda b: b["rank"]):
        change = book["rank_change"]
        if change is None:
            change_str = "NEW" if book["match_status"] == "matched" else "-"
        elif change > 0:
            change_str = f"▲{change}"
        elif change < 0:
            change_str = f"▼{abs(change)}"
        else:
            change_str = "-"
        print(
            f"{book['rank']}위 | {book['title']} | {book['author']} | "
            f"{book['publisher']} | {book.get('isbn13') or '(없음)'} | {change_str}"
        )


if __name__ == "__main__":
    main()

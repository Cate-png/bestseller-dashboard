"""
교보문고 국내도서 종합(주간) 베스트셀러 TOP100 수집 -> Supabase 저장 스크립트

기반: test_kyobo_bestseller.py 에서 실제로 검증된 로직을 그대로 재사용합니다.
- 목록 페이지: Playwright로 렌더링 후, product.kyobobook.co.kr/detail/ 링크를 감싼
  <img alt="도서명">에서 제목을 추출 (검증됨, '새창보기' 오탐 문제 해결된 버전)
- 상세 페이지 ISBN13: 표지 이미지 파일명 패턴 /pdt/{ISBN13}.  (검증됨)
- 상세 페이지 저자: <meta property="eg:brandName" content="..."> (검증됨)
- 상세 페이지 출판사: href에 pbcmCode= 를 포함하는 링크의 텍스트 (검증됨)
- 상세 페이지 요청 간 딜레이 2초 (기존과 동일)

정직하게 밝혀야 할 부분 (TOP100 확장 관련):
- 목록 페이지를 처음 열면 기본으로 약 30권 정도만 렌더링되는 것까지는 확인했지만,
  나머지(TOP100까지)를 어떤 방식으로 더 불러오는지(무한스크롤/더보기 버튼/페이지
  파라미터)는 이번 대화에서 실제로 확인한 적이 없습니다.
- 그래서 특정 버튼 선택자를 추측해서 넣는 대신, "아래로 스크롤을 반복하며 새로
  로드되는 도서가 있는지 확인"하는 범용적인 방식으로 시도합니다. 만약 이 사이트가
  스크롤이 아닌 다른 방식(예: 더보기 버튼 클릭)으로 추가 로드된다면, 100권을 못
  채우고 스크롤이 멈출 것이고, 그 경우 정확히 몇 권까지 로드됐는지와 함께
  진단 메시지를 출력합니다. 그 경우에도 로드된 만큼은 정상적으로 저장합니다
  (요청하신 '일부 실패해도 나머지는 저장' 원칙과 동일하게 처리).

collection_runs 기록 방식은 test_save_aladin.py와 동일합니다: status 컬럼이
'success'/'failed'만 허용하므로, 전체 수집이 끝난 뒤 결과를 한 번에 기록합니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY

상세 페이지 조회 동시성(concurrency)에 대해:
- 상세 페이지 100번 순차 방문이 전체 실행 시간의 대부분을 차지해서, 이 부분만
  concurrency_utils.enrich_details_concurrently()를 통해 제한된 동시 실행
  (DETAIL_CONCURRENCY=4)으로 바꿨습니다. 목록 페이지 파싱, 상세 페이지
  파싱(fetch_detail), Supabase 저장 방식, rank_change 계산은 전혀 바뀌지
  않았습니다 - 상세 페이지를 "몇 개씩 동시에 방문하느냐"만 바뀐 것입니다.
"""

import os
import re
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

BOOKSTORE = "교보문고"
CATEGORY = "종합"

LIST_URL = "https://store.kyobobook.co.kr/bestseller/total/weekly"
TARGET_COUNT = 100
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

GET_HREF_JS = "(img) => img.closest('a') ? img.closest('a').getAttribute('href') : null"
ISBN13_PATTERN = re.compile(r"/pdt/(\d{13})\.")

IMG_SELECTOR = "a[href*='product.kyobobook.co.kr/detail/'] img"


# ─────────────────────────────────────────────
# 아래는 test_kyobo_bestseller.py에서 실제로 검증된 로직 그대로입니다.
# ─────────────────────────────────────────────

def fetch_detail(page, url: str):
    page.goto(url, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    html = page.content()

    isbn13 = ""
    m = ISBN13_PATTERN.search(html)
    if m:
        isbn13 = m.group(1)

    author = ""
    author_meta = page.locator("meta[property='eg:brandName']")
    if author_meta.count() > 0:
        author = (author_meta.first.get_attribute("content") or "").strip()

    publisher = ""
    publisher_link = page.locator("a[href*='pbcmCode=']")
    if publisher_link.count() > 0:
        publisher = publisher_link.first.inner_text().strip()

    return {"isbn13": isbn13 or None, "author": author, "publisher": publisher}


# ─────────────────────────────────────────────
# 여기부터 이번에 새로 추가한 부분 (TOP100 스크롤 로딩 + Supabase 저장)
# ─────────────────────────────────────────────

def load_top100_list(page):
    """확인된 방식대로 ?page=1 ~ ?page=5 를 순서대로 열어 페이지당 20권씩,
    총 최대 100권을 모읍니다. (debug_kyobo_network.py로 실제 확인된 방식:
    href='?page=2' 클릭 시 실제로 21~40위가 로드됨을 확인함.)"""
    books = []
    seen_urls = set()
    rank = 1
    pages_needed = -(-TARGET_COUNT // 20)  # TARGET_COUNT=100 -> 5페이지

    for page_num in range(1, pages_needed + 1):
        page_url = LIST_URL if page_num == 1 else f"{LIST_URL}?page={page_num}"
        print(f"{page_num}페이지 로딩 중... ({page_url})")
        page.goto(page_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        imgs = page.locator(IMG_SELECTOR)
        count = imgs.count()
        page_added = 0
        for i in range(count):
            if rank > TARGET_COUNT:
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
            page_added += 1

        print(f"   -> {page_num}페이지에서 {page_added}권 추가 (누적 {len(books)}권)")

        if page_added == 0:
            print(f"   진단: {page_num}페이지에서 새로 추가된 도서가 없습니다. 여기서 중단합니다.")
            break

    if len(books) < TARGET_COUNT:
        print(f"진단: 목표({TARGET_COUNT}권)를 채우지 못했습니다. 우선 로드된 {len(books)}권만 진행합니다.")

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
    """상세 페이지 방문을 DETAIL_CONCURRENCY(기본 4)개씩 동시 처리합니다.
    개별 도서 파싱 로직(_fetch_one_detail -> fetch_detail)은 기존과 동일합니다."""
    return enrich_details_concurrently(
        books,
        fetch_one=_fetch_one_detail,
        user_agent=USER_AGENT,
        concurrency=DETAIL_CONCURRENCY,
        request_delay=DETAIL_REQUEST_DELAY,
    )


def get_previous_ranks(client):
    # rankings을 직접 조회합니다(예전에는 collection_runs에서 "가장 최근 run"을 먼저 찾았지만,
    # 분야별(카테고리) 수집이 별도 run으로 추가되면서 "이 서점의 가장 최근 run"이 항상
    # 종합 수집이라는 보장이 없어졌습니다. category="종합" 스냅샷만 정확히 찾기 위해
    # rankings에서 바로 조회하도록 바꿨습니다. 종합 TOP100 결과 자체는 동일합니다.)
    latest = (
        client.table("rankings")
        .select("collected_at")
        .eq("bookstore", BOOKSTORE)
        .eq("category", CATEGORY)
        .order("collected_at", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return {}

    latest_collected_at = latest.data[0]["collected_at"]
    prev_rankings = (
        client.table("rankings")
        .select("isbn13, rank")
        .eq("bookstore", BOOKSTORE)
        .eq("category", CATEGORY)
        .eq("collected_at", latest_collected_at)
        .execute()
    )
    return {row["isbn13"]: row["rank"] for row in prev_rankings.data if row["isbn13"]}


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("직전 교보문고 수집 결과 조회 중 (순위 변동 계산용)...")
    prev_ranks = get_previous_ranks(client)
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

            books = load_top100_list(page)
            if not books:
                raise RuntimeError("목록에서 도서를 하나도 추출하지 못했습니다.")

            browser.close()

        print(
            f"\n목록 수집 성공: {len(books)}권. "
            f"상세 페이지를 동시성={DETAIL_CONCURRENCY}로 조회합니다.\n"
        )
        books = enrich_with_details(books)
    except Exception as e:
        error_message = str(e)
        print(f"\n교보문고 수집이 완전히 실패했습니다: {error_message}")

    for book in books:
        isbn13 = book.get("isbn13")
        if isbn13 and isbn13 in prev_ranks:
            book["rank_change"] = prev_ranks[isbn13] - book["rank"]
        else:
            book["rank_change"] = None
        book["match_status"] = "matched" if isbn13 else "no_isbn"

    status = "success" if books else "failed"

    run_insert = (
        client.table("collection_runs")
        .insert({
            "bookstore": BOOKSTORE,
            "status": status,
            "error_message": error_message,
            "item_count": len(books),
        })
        .execute()
    )
    run_id = run_insert.data[0]["id"]
    print(f"collection_runs 기록 완료. run_id={run_id}, status={status}")

    if not books:
        print("저장할 도서 데이터가 없어 books/rankings 저장은 건너뜁니다.")
        sys.exit(1)

    books_payload = []
    seen_isbn = set()
    for book in books:
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
            "category": CATEGORY,
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
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"rankings 테이블 저장 완료: {rankings_saved}건")

    print("\n" + "=" * 80)
    print(f"교보문고 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"수집 권수: {len(books)}")
    print(f"books 저장/갱신 권수: {books_saved}")
    print(f"rankings 저장 권수: {rankings_saved}")
    print("=" * 80)
    print("TOP20 (순위 | 도서명 | 저자 | 출판사 | ISBN13 | 등락)")
    print("=" * 80)
    for book in sorted(books, key=lambda b: b["rank"])[:20]:
        change = book["rank_change"]
        if change is None:
            change_str = "NEW" if book["match_status"] == "matched" else "-"
        elif change > 0:
            change_str = f"▲{change}"
        elif change < 0:
            change_str = f"▼{abs(change)}"
        else:
            change_str = "-"
        print(f"{book['rank']}위 | {book['title']} | {book['author']} | "
              f"{book['publisher']} | {book.get('isbn13') or '(없음)'} | {change_str}")


if __name__ == "__main__":
    main()

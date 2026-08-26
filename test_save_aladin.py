"""
알라딘 국내도서 종합 베스트셀러 TOP100 수집 -> Supabase 저장 스크립트

기반: test_aladin_bestseller.py 에서 실제로 검증된 로직을 그대로 재사용합니다.
- 목록 페이지 선택자: div.ss_book_box / a.bo3 (검증됨)
- 상세 페이지 ISBN13: 메타 태그 og:barcode 또는 books:isbn (검증됨)
- 상세 페이지 저자/출판사: href의 AuthorSearch= / PublisherSearch= 패턴 (검증됨)
- 상세 페이지 요청 간 딜레이 2초 (기존과 동일)

이번에 새로 추가한 부분:
- TOP10 -> TOP100 확장 (알라딘은 한 번에 최대 50개까지만 주므로 page=1, page=2
  두 번 호출해서 합칩니다. 이 페이지네이션 방식은 이전 대화에서 실제 사이트의
  '51위' 링크가 page=2&cnt=1000&SortOrder=1 형태였음을 확인해서 쓰는 것입니다.)
- Supabase 저장 (collection_runs / books / rankings)
- 직전 알라딘 스냅샷과 비교한 rank_change 계산

collection_runs 기록 방식에 대해 미리 밝혀둡니다:
- 요청하신 스키마의 status 컬럼은 CHECK 제약으로 'success' 또는 'failed'만 허용됩니다
  ('진행중' 같은 중간 상태가 없습니다). 그래서 "시작 정보"를 별도 행으로 먼저 넣지 않고,
  전체 수집이 끝난 시점에 결과(success/failed)를 한 번에 기록하는 방식으로 구현했습니다.
  중간에 상세 페이지 일부가 실패해도 전체를 중단하지 않고 계속 진행하며, 최종적으로
  하나라도 수집됐으면 success로, 목록 자체를 못 가져오는 등 완전히 실패했으면 failed로
  기록합니다.

페이지 요청 방식(requests -> Playwright)에 대해:
- 처음에는 requests로 목록/상세 페이지를 가져왔는데, 로컬에서는 문제없이 동작했지만
  GitHub Actions에서만 "403 Client Error: Forbidden"으로 실패했습니다. requests는
  일반 브라우저와 TLS/HTTP 헤더 지문이 달라 알라딘의 봇 차단에 걸리기 쉬운데,
  같은 워크플로에서 교보문고는 이미 Playwright(Chromium)로 문제없이 수집되고 있어서
  (동일한 GitHub Actions 러너 IP인데도 정상 동작), 알라딘도 requests 대신 실제
  Chromium(Playwright)으로 페이지를 열어 HTML을 가져오도록 바꿨습니다. 파싱 로직
  (parse_list / parse_detail)과 Supabase 저장 방식은 전혀 바꾸지 않았습니다 - 그저
  HTML을 "어떻게 가져오느냐"만 바뀐 것입니다.
- 그래도 일시적으로 403/차단 응답이 오는 경우를 대비해, 페이지 요청 하나당 짧은
  대기 후 한 번 더 재시도하는 retry 로직을 추가했습니다.

상세 페이지 조회 동시성(concurrency)에 대해:
- 상세 페이지 100번 순차 방문이 전체 실행 시간의 대부분을 차지해서, 이 부분만
  concurrency_utils.enrich_details_concurrently()를 통해 제한된 동시 실행
  (DETAIL_CONCURRENCY=4)으로 바꿨습니다. 목록 페이지 파싱, 상세 페이지
  파싱(parse_detail), Supabase 저장 방식, rank_change 계산은 전혀 바뀌지
  않았습니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import random
import sys
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup

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

BOOKSTORE = "알라딘"
CATEGORY = "종합"

LIST_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
CONTEXT_KWARGS = {"locale": "ko-KR", "timezone_id": "Asia/Seoul"}

DETAIL_REQUEST_DELAY = 2.0
TARGET_COUNT = 100
PAGE_RETRY_COUNT = 3
PAGE_RETRY_BASE_DELAY = 4.0
DETAIL_CONCURRENCY = 4


# ─────────────────────────────────────────────
# 아래 parse_list / parse_detail 함수는 test_aladin_bestseller.py에서 실제로
# 검증된 로직을 그대로 가져온 것입니다 (HTML 파싱 부분은 바뀐 것이 없습니다).
# (parse_list에 페이지네이션을 위한 start_rank 인자만 추가했습니다.)
# ─────────────────────────────────────────────

def goto_with_retry(page, url: str, retries: int = PAGE_RETRY_COUNT) -> str:
    """Playwright 페이지로 url을 열어 HTML을 반환합니다. 403 등 일시적인 차단
    응답에 대비해, 실패하면 점점 길어지는 대기 후 재시도합니다."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = page.goto(url, timeout=30000)
            status = response.status if response else None
            if status and status >= 400:
                raise RuntimeError(f"HTTP {status} 응답")
            page.wait_for_timeout(800)
            return page.content()
        except Exception as e:
            last_error = e
            if attempt < retries:
                delay = PAGE_RETRY_BASE_DELAY * attempt + random.uniform(0, 2.0)
                print(
                    f"      -> 페이지 요청 실패({e}), {delay:.1f}초 대기 후 재시도 "
                    f"({attempt}/{retries})"
                )
                time.sleep(delay)
    raise RuntimeError(f"페이지 요청이 {retries}번 모두 실패했습니다: {last_error}")


def fetch_list_page(page, page_num: int) -> str:
    params = {
        "BestType": "Bestseller",
        "BranchType": "1",   # 국내도서
        "CID": "0",          # 0 = 종합(전체 분야)
    }
    if page_num > 1:
        params["page"] = str(page_num)
        params["cnt"] = "1000"
        params["SortOrder"] = "1"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    return goto_with_retry(page, url)


def parse_list(html: str, start_rank: int):
    soup = BeautifulSoup(html, "html.parser")
    boxes = soup.select("div.ss_book_box")

    if not boxes:
        print(f"진단: page 시작순위 {start_rank}에서 'div.ss_book_box'를 찾지 못했습니다.")
        return []

    books = []
    rank = start_rank
    for box in boxes:
        title_tag = box.select_one("a.bo3")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        url = title_tag.get("href", "")
        if url and url.startswith("/"):
            url = "https://www.aladin.co.kr" + url
        # 표지 이미지 URL("표지 보기" 전용, 순위/제목/URL 파싱과는 무관).
        # 목록 페이지 안에 이미 있는 <img class="front_cover">를 그대로
        # 읽기만 할 뿐 별도 요청은 없습니다. 표시 크기에 따라 클래스가
        # "i_cover"인 경우도 실측 확인해 함께 선택합니다. 이 두 클래스가
        # 아닌 img.left_cover는 책 옆면 그림자 장식용이라 표지가 아니라서
        # 제외합니다. 못 찾으면 None으로 두고(수집 실패로 처리하지 않음),
        # 화면에서는 표지 없음으로 표시됩니다.
        cover_tag = box.select_one("img.front_cover, img.i_cover")
        cover_url = cover_tag.get("src", "").strip() if cover_tag else ""
        books.append({
            "rank": rank,
            "title": title,
            "url": url,
            "cover_url": cover_url or None,
        })
        rank += 1

    return books


def fetch_detail_page(page, url: str) -> str:
    return goto_with_retry(page, url)


def parse_detail(html: str):
    soup = BeautifulSoup(html, "html.parser")

    isbn13 = ""
    meta_isbn = soup.find("meta", attrs={"property": "og:barcode"})
    if not meta_isbn:
        meta_isbn = soup.find("meta", attrs={"property": "books:isbn"})
    if meta_isbn and meta_isbn.get("content"):
        isbn13 = meta_isbn["content"].strip()

    authors = []
    publisher = ""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if publisher:
            break
        if "AuthorSearch=" in href:
            text = a.get_text(strip=True)
            if text and text not in authors:
                authors.append(text)
        elif "PublisherSearch=" in href:
            publisher = a.get_text(strip=True)

    # 분야(카테고리) breadcrumb: div.conts_info_list2 안의 <a> 링크들이
    # "국내도서 > 대분류 > 중분류 > ..." 순서로 들어있음을 실측 확인했습니다
    # (예: ["국내도서", "인문학", "서양철학", "고대철학", "고대철학 일반",
    # "접기"] - 마지막 "접기"는 펼치기/접기 버튼이라 카테고리가 아님).
    # 2번째 값(index 1, "국내도서" 바로 다음)을 대분류로 씁니다 - 교보
    # saleCmdtClstName과 같은 granularity(대분류 1단계)로 맞추기 위함입니다.
    store_category = None
    breadcrumb = soup.select_one("div.conts_info_list2")
    if breadcrumb:
        crumb_links = breadcrumb.find_all("a")
        if len(crumb_links) >= 2:
            text = crumb_links[1].get_text(strip=True)
            store_category = text or None

    return {
        "author": ", ".join(authors),
        "publisher": publisher,
        "isbn13": isbn13,
        "store_category": store_category,
    }


# ─────────────────────────────────────────────
# 여기부터 이번에 새로 추가한 부분
# ─────────────────────────────────────────────

def collect_top100(page):
    """목록 2페이지(1~50, 51~100)를 가져와 TOP100 도서 목록(제목/URL/순위)을 만듭니다."""
    all_books = []
    for page_num, start_rank in ((1, 1), (2, 51)):
        html = fetch_list_page(page, page_num)
        books = parse_list(html, start_rank)
        if not books:
            raise RuntimeError(f"목록 페이지 {page_num}에서 도서를 하나도 추출하지 못했습니다.")
        all_books.extend(books)
    return all_books[:TARGET_COUNT]


def _fetch_one_detail(page, book):
    """개별 도서 조회가 실패해도 전체를 중단하지 않고, 그 도서만 빈 정보로 남깁니다."""
    try:
        html = fetch_detail_page(page, book["url"])
        detail = parse_detail(html)
    except Exception as e:
        print(f"   -> 상세 페이지 조회 실패, 이 도서는 제목/URL만 저장합니다: {e}")
        detail = {"author": "", "publisher": "", "isbn13": "", "store_category": None}

    book["author"] = detail["author"]
    book["publisher"] = detail["publisher"]
    book["isbn13"] = detail["isbn13"] or None
    book["store_category"] = detail.get("store_category")


def enrich_with_details(books):
    """상세 페이지 방문을 DETAIL_CONCURRENCY(기본 4)개씩 동시 처리합니다.
    개별 도서 파싱 로직(_fetch_one_detail -> fetch_detail_page/parse_detail)은
    기존과 동일합니다."""
    return enrich_details_concurrently(
        books,
        fetch_one=_fetch_one_detail,
        user_agent=HEADERS["User-Agent"],
        concurrency=DETAIL_CONCURRENCY,
        request_delay=DETAIL_REQUEST_DELAY,
        context_kwargs=CONTEXT_KWARGS,
    )


def get_previous_ranks(client):
    """가장 최근 성공한 알라딘 '종합' 수집 스냅샷의 isbn13 -> rank 매핑을 가져옵니다.
    이전 수집이 없으면 빈 dict를 반환합니다 (전부 신규진입 처리).

    rankings을 직접 조회합니다(예전에는 collection_runs에서 "가장 최근 run"을 먼저
    찾았지만, 분야별(카테고리) 수집이 별도 run으로 추가되면서 "이 서점의 가장 최근
    run"이 항상 종합 수집이라는 보장이 없어졌습니다. category="종합" 스냅샷만
    정확히 찾기 위해 rankings에서 바로 조회하도록 바꿨습니다. 종합 TOP100 결과
    자체는 동일합니다.)"""
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
    return {
        row["isbn13"]: row["rank"]
        for row in prev_rankings.data
        if row["isbn13"]
    }


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    # 1. 직전 스냅샷 순위 확보 (rank_change 계산용) - 새 데이터를 쓰기 전에 먼저 조회
    print("직전 알라딘 수집 결과 조회 중 (순위 변동 계산용)...")
    prev_ranks = get_previous_ranks(client)
    print(f"직전 스냅샷 도서 수: {len(prev_ranks)}권\n")

    # 2~3. TOP100 수집 + 상세정보 보강
    collected_at = datetime.now(timezone.utc).isoformat()
    error_message = None
    books = []

    try:
        # 목록 페이지는 별도 브라우저로 열었다 닫습니다(상세 페이지 동시 조회용
        # 워커 스레드들이 각자 별도의 Playwright 인스턴스를 쓰기 때문에, 목록용
        # 인스턴스와 시간상 겹치지 않게 해서 더 단순하고 안전하게 구성했습니다).
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

            print("알라딘 TOP100 목록 수집 중...")
            books = collect_top100(page)
            browser.close()

        print(
            f"목록 수집 성공: {len(books)}권. "
            f"상세 페이지를 동시성={DETAIL_CONCURRENCY}로 조회합니다.\n"
        )
        books = enrich_with_details(books)
    except Exception as e:
        error_message = str(e)
        print(f"\n알라딘 수집이 완전히 실패했습니다: {error_message}")

    # 순위 변동 계산 (isbn13 있는 도서만)
    for book in books:
        isbn13 = book.get("isbn13")
        if isbn13 and isbn13 in prev_ranks:
            book["rank_change"] = prev_ranks[isbn13] - book["rank"]
        else:
            book["rank_change"] = None
        book["match_status"] = "matched" if isbn13 else "no_isbn"

    status = "success" if books else "failed"

    # 4. collection_runs 기록 (전체 처리 완료 후 결과를 기록)
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

    # 5. books upsert (isbn13 있는 도서만, first_seen_at은 페이로드에서 제외해서
    #    신규 삽입 시에만 DB 기본값 now()가 적용되고 기존 행은 덮어쓰지 않게 함)
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
        result = (
            client.table("books")
            .upsert(books_payload, on_conflict="isbn13")
            .execute()
        )
        books_saved = len(result.data)
    print(f"books 테이블 upsert 완료: {books_saved}건")

    # 7~8. rankings 저장 (isbn13 없는 도서도 match_status='no_isbn'으로 함께 저장)
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
            "store_category": book.get("store_category"),
            "cover_url": book.get("cover_url"),
        }
        for book in books
    ]
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"rankings 테이블 저장 완료: {rankings_saved}건")

    # rankings 저장이 실제로 끝난 직후의 시각을 collection_runs.run_at에 다시
    # 기록합니다. run_at은 원래 이 run 레코드를 만들 때 DB 기본값(now())으로
    # 채워지는데, 그 시점은 books/rankings 저장 이전이라 "실제 저장 완료 시각"과는
    # 다릅니다. collected_at(각 rankings 행의 회차 식별자로 계속 쓰이는 값)은
    # 건드리지 않고, 화면 표시용으로만 쓰이는 run_at만 갱신합니다.
    saved_at = datetime.now(timezone.utc).isoformat()
    client.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id).execute()
    print(f"collection_runs.run_at을 실제 저장 완료 시각으로 갱신: {saved_at}")

    # 11. 최종 콘솔 출력
    print("\n" + "=" * 80)
    print(f"알라딘 수집 성공 여부: {status}")
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

"""예스24 실시간베스트 수집 -> Supabase realtime_rankings 저장.

기존 종합/분야별 스크립트(test_save_yes24.py, test_save_yes24_category.py)는
apis.yes24.com의 사설 API를 requests로 호출하는 방식이었지만, 이 실시간
베스트는 그 API와는 별개의 페이지(yes24.com/Product/Category/
RealTimeBestSeller)이고 대응하는 API 파라미터를 확인하지 못했습니다.
짐작으로 API 파라미터를 추측해서 쓰는 대신, diagnose_realtime.py로
GitHub Actions에서 실제 HTML 구조를 확인한 뒤 그 결과를 그대로 반영해
Playwright + BeautifulSoup으로 이 페이지를 직접 파싱합니다. 기존
test_save_yes24.py / test_save_yes24_category.py는 전혀 수정하지 않습니다.

목록 페이지: https://www.yes24.com/Product/Category/RealTimeBestSeller?categoryNumber=001
("실시간베스트" - 사이트 자체 페이지 제목 및 실사용자 후기 기준 1시간마다
갱신됨)

diagnose_realtime.py로 실제로 확인한 내용:
- 도서 항목은 div.itemUnit 단위로 나오고(이 categoryNumber=001 페이지에서
  100건), 각 항목의 span.gd_res 값으로 분류가 표시됩니다.
  (처음엔 'eBook19,800원' 같은 링크가 별도 순위 항목처럼 보였지만, 실제로는
  종이책 itemUnit 안에 들어있는 "eBook로 구매" 보조 버튼 링크였을 뿐이었음)

- [중요, 추가 조사] gd_res != '[도서]'면 전부 걸러내던 기존 필터가 만화
  분야 데이터를 통째로 누락시키고 있었습니다. 실제 페이지(100건)를 직접
  파싱해 gd_res 값 분포를 확인한 결과 '[도서]' 87건, '[만화]' 10건,
  '[잡지]' 3건으로 나뉘어 있었습니다. '[만화]'도 이 실시간베스트 목록에
  함께 랭크되는 정상적인 국내도서 카테고리 항목(만화책)이므로
  BOOK_GD_RES_VALUES에 포함시켰습니다. '[잡지]'는 정기간행물이라 기존과
  동일하게 계속 제외합니다.
- 저자(span.info_auth)/출판사(span.info_pub)는 목록 페이지 안에 이미 들어
  있어 별도 상세페이지 방문 없이 바로 가져올 수 있습니다.
- ISBN13은 목록 페이지엔 없고, 상품 상세페이지의
  <meta property="books:isbn" content="..."> 에서 확인됩니다(알라딘
  스크래퍼가 쓰는 것과 동일한 meta 태그 패턴).

기존 weekly/분야별 시스템과의 분리:
- rankings / collection_runs / books 테이블에는 전혀 쓰지 않고,
  realtime_rankings / realtime_collection_runs 테이블에만 저장합니다.
- YES24_API_KEY도 필요 없습니다(이 페이지는 공개 웹페이지라 API 키 불필요).
- test_save_yes24.py, test_save_yes24_category.py, categories.py,
  collect.yml(매일 06시 정기 수집)은 전혀 건드리지 않습니다.

2026-08-25(정책 변경): gd_res 기준 비도서 판별('[잡지]' 등)로 순위권에서
아예 제외하던 것을 그만뒀습니다(이 상수/함수는 test_save_yes24_daily.py도
그대로 import해서 씁니다). 대시보드가 서점의 전체 트렌드를 보여주는
용도이므로 비도서도 유의미한 신호로 보고, item_type 컬럼(book/magazine/
non_book)에 판별 결과만 남겨서 화면에서 시각적으로만(회색) 구분합니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
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

from bs4 import BeautifulSoup

from concurrency_utils import enrich_details_concurrently

BOOKSTORE = "예스24"
LIST_URL = "https://www.yes24.com/Product/Category/RealTimeBestSeller?categoryNumber=001"
TARGET_COUNT = 100  # diagnose_realtime.py로 확인된, 이 페이지의 노출 개수(div.itemUnit 100건)
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

RANK_PATTERN = re.compile(r"\d+")

# 실측(diagnose_realtime.py, gd_res 값 분포 확인)으로 확인된, 도서로 인정할
# span.gd_res 값. 2026-08-25부터는 '[잡지]'(정기간행물) 등 그 외 값도
# 더 이상 순위권에서 제외하지 않고, item_type만 구분해서 저장합니다
# (정책 변경 - 모듈 docstring 참고).
BOOK_GD_RES_VALUES = {"[도서]", "[만화]"}


def classify_item_type(gd_res_text):
    if gd_res_text in BOOK_GD_RES_VALUES:
        return "book"
    if gd_res_text == "[잡지]":
        return "magazine"
    return "non_book"


def load_realtime_list(page):
    page.goto(LIST_URL, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    html = page.content()

    soup = BeautifulSoup(html, "html.parser")
    books = []
    for unit in soup.select("div.itemUnit")[:TARGET_COUNT]:
        gd_res = unit.select_one("span.gd_res")
        gd_res_text = gd_res.get_text(strip=True) if gd_res else ""
        item_type = classify_item_type(gd_res_text)

        rank_tag = unit.select_one("em.ico.rank")
        rank_match = RANK_PATTERN.search(rank_tag.get_text(strip=True)) if rank_tag else None
        if not rank_match:
            continue
        rank = int(rank_match.group())

        name_tag = unit.select_one("a.gd_name")
        title = name_tag.get_text(strip=True) if name_tag else ""
        href = name_tag.get("href", "") if name_tag else ""
        if href.startswith("/"):
            href = "https://www.yes24.com" + href
        if not title or not href:
            continue

        author_links = unit.select("span.info_auth a")
        author = ", ".join(a.get_text(strip=True) for a in author_links)

        publisher_tag = unit.select_one("span.info_pub a")
        publisher = publisher_tag.get_text(strip=True) if publisher_tag else ""

        books.append(
            {
                "rank": rank,
                "title": title,
                "url": href,
                "author": author,
                "publisher": publisher,
                "item_type": item_type,
            }
        )

    books.sort(key=lambda b: b["rank"])
    return books


def fetch_isbn13(page, url):
    page.goto(url, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1000)

    meta = page.locator("meta[property='books:isbn']")
    if meta.count() > 0:
        content = meta.first.get_attribute("content")
        if content:
            return content.strip()
    return None


def _fetch_one_detail(page, book):
    try:
        book["isbn13"] = fetch_isbn13(page, book["url"])
    except Exception as e:
        print(f"   -> 상세 페이지 조회 실패, 이 도서는 ISBN 없이 저장합니다: {e}")
        book["isbn13"] = None


def enrich_with_isbn(books):
    return enrich_details_concurrently(
        books,
        fetch_one=_fetch_one_detail,
        user_agent=USER_AGENT,
        concurrency=DETAIL_CONCURRENCY,
        request_delay=DETAIL_REQUEST_DELAY,
    )


def get_previous_realtime_ranks(client):
    """직전 회차의 (isbn13, url) -> rank 매핑을 돌려줍니다.

    isbn13만으로 매핑하면 안 됩니다 - 종이책/전자책처럼 같은 ISBN13을 공유하는
    서로 다른 상품이 리스트에 함께 들어있으면(교보문고에서 실측 확인된 사례),
    isbn13만 키로 쓸 경우 두 상품이 한 딕셔너리 키에서 충돌해 서로의 순위를
    덮어써 등락이 크게 틀어집니다. url은 상품(에디션) 단위로 고유하므로
    (isbn13, url) 조합을 키로 써서 이런 충돌을 막습니다. 예스24는 현재
    데이터에서 이 중복이 확인되지는 않았지만, 동일한 코드 패턴이라 잠재적으로
    같은 문제가 생길 수 있어 함께 방어합니다.
    """
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
        .select("isbn13, url, rank")
        .eq("bookstore", BOOKSTORE)
        .eq("collected_at", latest_collected_at)
        .execute()
    )
    return {
        (row["isbn13"], row["url"]): row["rank"]
        for row in prev.data
        if row["isbn13"]
    }


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("직전 예스24 실시간 수집 결과 조회 중 (순위 변동 계산용)...")
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
            print("예스24 실시간베스트 목록 수집 중...")
            books = load_realtime_list(page)
            browser.close()

        if not books:
            raise RuntimeError("실시간 목록에서 도서를 하나도 추출하지 못했습니다.")

        print(
            f"목록 수집 성공: {len(books)}권. "
            f"ISBN 확인을 위해 상세 페이지를 동시성={DETAIL_CONCURRENCY}로 조회합니다.\n"
        )
        books = enrich_with_isbn(books)
    except Exception as e:
        error_message = str(e)
        print(f"\n예스24 실시간 수집이 완전히 실패했습니다: {error_message}")

    for book in books:
        isbn13 = book.get("isbn13")
        key = (isbn13, book.get("url"))
        if isbn13 and key in prev_ranks:
            book["rank_change"] = prev_ranks[key] - book["rank"]
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
            "item_type": book.get("item_type"),
        }
        for book in books
    ]
    rankings_result = client.table("realtime_rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"realtime_rankings 저장 완료: {rankings_saved}건")

    print("\n" + "=" * 80)
    print(f"예스24 실시간 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"수집 권수: {len(books)}")
    print(f"realtime_rankings 저장 권수: {rankings_saved}")
    print("=" * 80)
    print("실시간 TOP20 (순위 | 도서명 | 저자 | 출판사 | ISBN13 | 등락 | 유형)")
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
        print(
            f"{book['rank']}위 | {book['title']} | {book['author']} | "
            f"{book['publisher']} | {book.get('isbn13') or '(없음)'} | {change_str} | "
            f"{book.get('item_type')}"
        )


if __name__ == "__main__":
    main()

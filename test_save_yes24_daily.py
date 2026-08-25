"""예스24 종합 일간 베스트셀러 TOP100 수집 -> Supabase rankings(category="일간") 저장.

목록 페이지: https://www.yes24.com/product/category/daybestseller?categoryNumber=001&pageSize=100
("일별" 베스트 - 실측 확인한 페이지 설명 문구: "전일 온라인과 매장에서의
판매 데이터를 기준으로 집계되었습니다" - 매장 판매까지 포함한 진짜 "종합"
기준 일간 데이터입니다. 교보문고의 "온라인 베스트 일간"과 달리 모수 차이
없음.)

기존 종합/분야별 스크립트(test_save_yes24.py, test_save_yes24_category.py)는
apis.yes24.com의 제휴 API를 requests로 호출하지만, 이 일별 페이지는 그 API와
대응하는 파라미터를 이번 조사에서 확인하지 못했습니다(diagnose 결과 해당
페이지 로딩 중 apis.yes24.com 호출이 전혀 캡처되지 않음). 대신 실시간
스크립트(test_save_yes24_realtime.py)가 이미 검증해둔 "공개 웹페이지를
Playwright + BeautifulSoup으로 직접 파싱"하는 방식을 그대로 재사용합니다 -
실측으로 이 일별 페이지도 실시간 페이지와 동일하게 div.itemUnit 단위로
항목이 나오고 셀렉터(em.ico.rank, a.gd_name, span.gd_res, span.info_auth,
span.info_pub)가 100% 동일하게 동작함을 확인했습니다. URL에 pageSize=100을
붙이면 페이지네이션 없이 한 번에 100건이 로드되는 것도 확인했습니다(실시간
페이지는 기본값으로 이미 100건이라 이 파라미터가 필요 없었음).

ISBN13 상세페이지 조회(fetch_isbn13)와 동시성 유틸(enrich_with_isbn),
상품유형 판별(classify_item_type/BOOK_GD_RES_VALUES), USER_AGENT는
test_save_yes24_realtime.py에서 그대로 import해서 재사용합니다(중복
구현하지 않음). 목록 파싱 함수만 이 파일의 LIST_URL을 쓰도록 별도로 둡니다
(원본 함수가 모듈 전역 LIST_URL을 직접 참조해 import만으로는 재사용할 수
없음 - test_save_kyobo_daily.py와 동일한 이유).

2026-08-25(정책 변경): '[잡지]' 등 비도서로 판별된 항목도 더 이상 순위권
에서 제외하지 않고, item_type 컬럼(book/magazine/non_book)만 채워서
저장합니다(test_save_yes24_realtime.py와 동일한 정책 변경).

rank_change 계산: 우리 자신의 직전 '일간' 스냅샷(rankings, category="일간")과
(isbn13, url) 기준으로 비교합니다(test_save_yes24_realtime.py와 동일한
충돌 방지 방식). 종합(주간)과는 category가 달라 절대 섞이지 않습니다.

기존 파일과의 분리:
- test_save_yes24.py, test_save_yes24_category.py, test_save_yes24_realtime.py,
  categories.py, collect.yml, collect-realtime.yml은 전혀 건드리지 않습니다.
- rankings/collection_runs는 기존 주간과 테이블을 공유하지만 category="일간"
  으로만 저장/조회합니다.
- realtime_rankings/realtime_collection_runs는 쓰지 않습니다.
- YES24_API_KEY도 필요 없습니다(공개 웹페이지라 API 키 불필요, 실시간
  스크립트와 동일).
- books 테이블은 건드립니다(rankings.isbn13 -> books.isbn13 외래키 제약
  때문에 필수 - 실측으로 이 upsert 없이는 rankings 저장이 전량 실패함을
  확인함). 기존 주간 스크립트와 동일한 upsert 방식을 그대로 씁니다.

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

from bs4 import BeautifulSoup

from test_save_yes24_realtime import (
    USER_AGENT,
    BOOK_GD_RES_VALUES,
    RANK_PATTERN,
    enrich_with_isbn,
    classify_item_type,
)

BOOKSTORE = "예스24"
CATEGORY = "일간"
LIST_URL = "https://www.yes24.com/product/category/daybestseller?categoryNumber=001&pageSize=100"
TARGET_COUNT = 100


def load_daily_list(page):
    """일별 베스트 페이지를 한 번 열어(pageSize=100) 최대 100권을 모읍니다.
    실시간 스크립트의 load_realtime_list()와 동일한 셀렉터를 이 파일의
    LIST_URL(일별 페이지)에 적용합니다."""
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


def get_previous_daily_ranks(client):
    """직전 '일간' 회차의 (isbn13, url) -> rank 매핑을 돌려줍니다. category="일간"
    으로만 필터링하므로 종합(주간)/분야별 데이터와는 절대 섞이지 않습니다."""
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
    prev = (
        client.table("rankings")
        .select("isbn13, url, rank")
        .eq("bookstore", BOOKSTORE)
        .eq("category", CATEGORY)
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

    print("직전 예스24 '일간' 수집 결과 조회 중 (순위 변동 계산용)...")
    prev_ranks = get_previous_daily_ranks(client)
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
            print("예스24 일별베스트 목록 수집 중...")
            books = load_daily_list(page)
            browser.close()

        if not books:
            raise RuntimeError("일별 목록에서 도서를 하나도 추출하지 못했습니다.")

        print(
            f"목록 수집 성공: {len(books)}권. "
            f"ISBN 확인을 위해 상세 페이지를 조회합니다.\n"
        )
        books = enrich_with_isbn(books)
    except Exception as e:
        error_message = str(e)
        print(f"\n예스24 일간 수집이 완전히 실패했습니다: {error_message}")

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
        print("저장할 도서 데이터가 없어 rankings 저장은 건너뜁니다.")
        sys.exit(1)

    # rankings.isbn13은 books.isbn13을 참조하는 외래키(FK)라서, rankings에
    # 넣기 전에 books에 먼저 upsert해둬야 합니다(실측: 이 upsert 없이
    # rankings.insert만 했더니 "violates foreign key constraint
    # rankings_isbn13_fkey"로 전량 실패함). realtime_rankings는 이 FK가
    # 없어서 실시간 스크립트는 books를 안 건드리지만, 여기서는 기존 주간
    # 스크립트와 동일하게 books upsert가 반드시 필요합니다.
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
            "item_type": book.get("item_type"),
        }
        for book in books
    ]
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"rankings 테이블 저장 완료(category=일간): {rankings_saved}건")

    saved_at = datetime.now(timezone.utc).isoformat()
    client.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id).execute()
    print(f"collection_runs.run_at을 실제 저장 완료 시각으로 갱신: {saved_at}")

    print("\n" + "=" * 70)
    print("예스24 일간 TOP20 저장 결과")
    print("=" * 70)
    for book in sorted(books, key=lambda b: b["rank"])[:20]:
        change = book["rank_change"]
        change_text = "-" if change is None else str(change)
        print(
            f'{book["rank"]:>3}위 | {book["title"]} | '
            f'{book["author"] or "-"} | {book["publisher"] or "-"} | '
            f'ISBN13 {book.get("isbn13") or "-"} | 등락 {change_text} | '
            f'유형 {book.get("item_type")}'
        )


if __name__ == "__main__":
    main()

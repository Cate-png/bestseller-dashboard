"""알라딘 종합 일간 베스트셀러("어제 베스트") TOP100 수집 ->
Supabase rankings(category="일간") 저장.

목록 페이지: https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=DailyBest
("어제 베스트" - 실측 확인한 페이지 설명 문구: "어제 하루 동안 가장 많은
고객들이 구매한..." - 매장 판매를 포함하는지는 명시돼 있지 않지만, 교보와
달리 "온라인"이라는 별도 카테고리 구분이 사이트 메뉴 구조에 없고 다른
베스트 유형들(주간 베스트 등, 기존 스크립트가 "종합"으로 쓰는 것)과 동일한
메뉴 레벨에 있어 같은 모수로 판단했습니다.)

기존 주간 스크립트(test_save_aladin.py)와 셀렉터/파싱 로직이 100% 동일함을
실측 확인했습니다(div.ss_book_box / a.bo3, page=2&cnt=1000&SortOrder=1
페이지네이션도 동일하게 동작 - 2페이지에서 51위 이후 50건 정상 로드).
그래서 parse_list/goto_with_retry/enrich_with_details/HEADERS/
CONTEXT_KWARGS를 그대로 재사용하고, 목록 페이지 요청 함수만 이 파일의
BestType=DailyBest URL을 쓰도록 별도로 둡니다(원본 fetch_list_page가 모듈
전역 상수로 BestType=Bestseller를 고정하고 있어 import만으로는 재사용 불가 -
test_save_kyobo_daily.py / test_save_yes24_daily.py와 동일한 이유).

rank_change 계산: 기존 주간 get_previous_ranks()(isbn13만 키로 씀)를
재사용하지 않고, (isbn13, url) 기준의 새 get_previous_daily_ranks()를
별도로 둡니다 - test_save_kyobo_realtime.py 등에서 실측 확인된 것과 동일한
이유로(같은 ISBN13을 공유하는 서로 다른 상품이 있을 수 있음), 새로 만드는
파일이니 처음부터 안전한 방식으로 구현합니다. category="일간"으로만
필터링하므로 종합(주간)과는 절대 섞이지 않습니다.

기존 파일과의 분리:
- test_save_aladin.py, test_save_aladin_category.py, test_save_aladin_realtime.py,
  categories.py, collect.yml, collect-realtime.yml은 전혀 건드리지 않습니다.
- rankings/collection_runs는 기존 주간과 테이블을 공유하지만 category="일간"
  으로만 저장/조회합니다.
- realtime_rankings/realtime_collection_runs는 쓰지 않습니다.

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

from test_save_aladin import (
    CONTEXT_KWARGS,
    HEADERS,
    DETAIL_CONCURRENCY,
    DETAIL_REQUEST_DELAY,
    TARGET_COUNT,
    goto_with_retry,
    parse_list,
    enrich_with_details,
)

BOOKSTORE = "알라딘"
CATEGORY = "일간"
LIST_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx"


def fetch_daily_list_page(page, page_num: int) -> str:
    params = {
        "BestType": "DailyBest",  # "어제 베스트" - 실측 확인된 종합 일간
        "BranchType": "1",  # 국내도서
    }
    if page_num > 1:
        # 주간 스크립트(fetch_list_page)의 2페이지 이후 파라미터와 동일 -
        # DailyBest에도 그대로 적용됨을 실측 확인함.
        params["page"] = str(page_num)
        params["cnt"] = "1000"
        params["SortOrder"] = "1"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    return goto_with_retry(page, url)


def collect_daily_top100(page):
    """목록 2페이지(1~50, 51~100)를 가져와 TOP100 도서 목록(제목/URL/순위)을
    만듭니다. 주간 스크립트의 collect_top100()과 동일한 구조입니다."""
    all_books = []
    for page_num, start_rank in ((1, 1), (2, 51)):
        html = fetch_daily_list_page(page, page_num)
        books = parse_list(html, start_rank)
        if not books:
            raise RuntimeError(f"목록 페이지 {page_num}에서 도서를 하나도 추출하지 못했습니다.")
        all_books.extend(books)
    return all_books[:TARGET_COUNT]


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

    print("직전 알라딘 '일간' 수집 결과 조회 중 (순위 변동 계산용)...")
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

            page = browser.new_page(
                user_agent=HEADERS["User-Agent"], **CONTEXT_KWARGS
            )

            print("알라딘 일간(어제 베스트) TOP100 목록 수집 중...")
            books = collect_daily_top100(page)
            browser.close()

        print(
            f"목록 수집 성공: {len(books)}권. "
            f"상세 페이지를 동시성={DETAIL_CONCURRENCY}로 조회합니다.\n"
        )
        books = enrich_with_details(books)
    except Exception as e:
        error_message = str(e)
        print(f"\n알라딘 일간 수집이 완전히 실패했습니다: {error_message}")

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
    print(f"rankings 테이블 저장 완료(category=일간): {rankings_saved}건")

    saved_at = datetime.now(timezone.utc).isoformat()
    client.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id).execute()
    print(f"collection_runs.run_at을 실제 저장 완료 시각으로 갱신: {saved_at}")

    print("\n" + "=" * 80)
    print(f"알라딘 일간 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"수집 권수: {len(books)}")
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

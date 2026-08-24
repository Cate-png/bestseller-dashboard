"""교보문고 종합 일간 베스트셀러 TOP100 수집 -> Supabase rankings(category="일간") 저장.

목록 페이지: https://store.kyobobook.co.kr/bestseller/online/daily

[중요] 데이터 성격 - 반드시 읽을 것:
교보문고 사이트 메뉴는 "종합 베스트"(주간/월간/연간)와 "온라인 베스트"
(일간/주간/월간)가 완전히 분리된 별도 카테고리입니다. "종합 베스트"에는
일간 옵션이 아예 없고, 일간은 오직 "온라인 베스트"에서만 제공됩니다.
즉 이 스크립트가 수집하는 데이터는 "온라인 판매분만 집계한 일간 순위"이며,
매장 판매를 포함한 진짜 "종합"(매장+온라인) 일간 데이터가 아닙니다
(실측: 페이지 타이틀도 "온라인 일간 베스트"). 기존 주간 스크립트
(test_save_kyobo.py)가 쓰는 "종합"(bestseller/total/weekly, 매장+온라인)과는
모수 자체가 다르다는 점을 감안해서 사용해야 합니다 - 예스24/알라딘의
일간은 매장+온라인 기준(실측 확인)이라 교보만 성격이 다릅니다.

내부 API(diagnose로 실제 캡처 확인):
  https://store.kyobobook.co.kr/api/gw/best/best-seller/online?page=N&per=20&period=001&dsplDvsnCode=000&dsplTrgtDvsnCode=001
기존 주간 API(.../total?period=002&bsslBksClstCode=A)와 응답 JSON 필드가
100% 동일함을 실측 확인(prstRnkn/frmrRnkn/cmdtCode/cmdtName/chrcName/
pbcmName/saleCmdtid 전부 동일 키). 그래서 test_save_kyobo.py의
fetch_best_seller_page()/item_to_book()을 그대로 재사용합니다 - 새로 파싱
로직을 만들지 않습니다.

rank_change 계산 방식(주간과의 차이):
item_to_book()이 채워주는 rank_change는 교보 API 자체의 frmrRnkn(교보 서버가
판단한 "이전 순위") 기반입니다. 이건 그대로 두지 않고, test_save_kyobo_realtime.py
와 동일한 방식으로 우리 자신의 직전 "일간" 스냅샷(rankings, category="일간")과
(isbn13, url) 기준으로 다시 비교해 덮어씁니다 - "직전 일간 회차와만 비교"를
명확히 보장하기 위함이며, 종합(주간)과는 category가 달라 절대 섞이지 않습니다.

기존 파일과의 분리:
- test_save_kyobo.py, test_save_kyobo_category.py, test_save_kyobo_realtime.py,
  categories.py, collect.yml, collect-realtime.yml은 전혀 건드리지 않습니다.
- rankings/collection_runs 테이블은 기존 주간과 공유하지만, category="일간"
  으로만 저장/조회하므로 category="종합"인 기존 행과 섞이지 않습니다.
- realtime_rankings/realtime_collection_runs는 전혀 쓰지 않습니다.
- books 테이블은 건드립니다(rankings.isbn13 -> books.isbn13 외래키 제약
  때문에 필수 - 실측으로 이 upsert 없이는 rankings 저장이 전량 실패함을
  확인함). 기존 주간 스크립트와 동일한 upsert 방식을 그대로 씁니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import sys

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

from datetime import datetime, timezone

from test_save_kyobo import USER_AGENT, fetch_best_seller_page, item_to_book

BOOKSTORE = "교보문고"
CATEGORY = "일간"
LIST_URL = "https://store.kyobobook.co.kr/bestseller/online/daily"
TARGET_COUNT = 100


def load_daily_top100_list(page):
    """page=1~5(per=20)를 순서대로 열어 최대 100권을 모읍니다. 주간 스크립트의
    load_top100_list()와 동일한 페이지네이션 구조를 온라인 일간 URL에 그대로
    적용합니다(실측으로 page=2도 정상 응답함을 확인)."""
    books = []
    pages_needed = -(-TARGET_COUNT // 20)  # 100 -> 5페이지

    for page_num in range(1, pages_needed + 1):
        page_url = LIST_URL if page_num == 1 else f"{LIST_URL}?page={page_num}"
        print(f"{page_num}페이지 로딩 중... ({page_url})")
        try:
            items = fetch_best_seller_page(page, page_url)
        except Exception as e:
            print(f"   진단: {page_num}페이지 조회 실패: {e}. 여기서 중단합니다.")
            break

        page_books = [item_to_book(item) for item in items if item.get("prstRnkn")]
        books.extend(page_books)
        print(f"   -> {page_num}페이지에서 {len(page_books)}권 추가 (누적 {len(books)}권)")

        if not page_books:
            print(f"   진단: {page_num}페이지에서 새로 추가된 도서가 없습니다. 여기서 중단합니다.")
            break

    if len(books) < TARGET_COUNT:
        print(f"진단: 목표({TARGET_COUNT}권)를 채우지 못했습니다. 우선 로드된 {len(books)}권만 진행합니다.")

    return books


def get_previous_daily_ranks(client):
    """직전 '일간' 회차의 (isbn13, url) -> rank 매핑을 돌려줍니다. category="일간"
    으로만 필터링하므로 종합(주간)/분야별 데이터와는 절대 섞이지 않습니다.
    (isbn13, url) 조합을 키로 쓰는 이유는 test_save_kyobo_realtime.py에서
    실측 확인된 것과 동일합니다 - 같은 책의 종이책/전자책이 ISBN13을
    공유하는 경우가 있어 isbn13만 키로 쓰면 서로의 순위를 덮어씁니다."""
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

    print("직전 교보문고 '일간' 수집 결과 조회 중 (순위 변동 계산용)...")
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
            books = load_daily_top100_list(page)
            browser.close()

        if not books:
            raise RuntimeError("목록에서 도서를 하나도 추출하지 못했습니다.")
    except Exception as e:
        error_message = str(e)
        print(f"\n교보문고 일간 수집이 완전히 실패했습니다: {error_message}")

    # item_to_book()이 채워준 frmrRnkn 기반 rank_change를 우리 자신의 직전
    # '일간' 스냅샷 비교값으로 덮어씁니다(주간과 절대 섞이지 않도록 category
    # 필터링된 prev_ranks만 사용).
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
    # 없어서 실시간 스크립트들은 books를 안 건드리지만, 여기서는 기존 주간
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
        }
        for book in books
    ]
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"rankings 테이블 저장 완료(category=일간): {rankings_saved}건")

    # rankings 저장이 실제로 끝난 직후의 시각을 collection_runs.run_at에
    # 기록합니다(주간 스크립트와 동일한 패턴 - "최종 업데이트" 화면 표시용).
    saved_at = datetime.now(timezone.utc).isoformat()
    client.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id).execute()
    print(f"collection_runs.run_at을 실제 저장 완료 시각으로 갱신: {saved_at}")

    print("\n" + "=" * 80)
    print(f"교보문고 일간 수집 성공 여부: {status}")
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
        print(
            f"{book['rank']}위 | {book['title']} | {book['author']} | "
            f"{book['publisher']} | {book.get('isbn13') or '(없음)'} | {change_str}"
        )


if __name__ == "__main__":
    main()

"""교보문고 "실시간 베스트셀러" 수집 -> Supabase realtime_rankings 저장.

TOP100 페이지네이션 + rank_change 계산 방식 전환 (diagnose_kyobo_realtime_api.py로
GitHub Actions에서 실제 네트워크 응답을 확인한 근거):

1. 목록 페이지 https://store.kyobobook.co.kr/bestseller/realtime 는 주간
   (best-seller/total)과는 별도의 내부 API
   api/gw/best/best-seller/realtime?page=N&per=20 로 채워지며, 응답에
   total=100이 명시되어 있고 page=1~5가 실제로 서로 다른 20건씩
   (1~20위/21~40위/.../81~100위, cmdtCode 중복 0건)을 반환하는 것을
   확인했습니다. 기존에 TOP20만 수집하던 것은 실제 페이지 한계가 아니라
   collector가 페이지네이션을 시도하지 않은 결과였습니다. 이제
   test_save_kyobo.py의 fetch_best_seller_page/item_to_book을 그대로
   재사용해 5페이지를 모두 수집합니다(카테고리 스크립트와 동일 패턴).
   상세페이지 방문은 애초에 하지 않습니다(API 응답에 저자/출판사/ISBN이
   이미 다 있음).

2. rank_change는 예스24/알라딘 실시간 수집기와 동일하게, realtime_rankings에
   저장해둔 우리 자신의 직전 스냅샷을 ISBN13 기준으로 찾아 비교해서
   계산합니다(get_previous_realtime_ranks). item_to_book이 채워주는
   frmrRnkn 기반 rank_change는 그대로 두되(공용 함수라 손대지 않음), 이
   스크립트에서 곧바로 우리 자신의 스냅샷 비교값으로 덮어씁니다.

   기존에는 교보 API 자체의 frmrRnkn(교보 서버가 계산한 "이전 순위")을
   그대로 썼는데, 실제 수집 로그 10회분을 ISBN13 기준으로 교차 대조한
   결과 예스24/알라딘은 100% 정확한 반면 교보만 6.3%(207쌍 중 13건)
   불일치가 확인됐습니다 - 예를 들어 같은 책이 두 회차에서 똑같이 8위인데
   등락이 ▼1→▼2로 바뀌거나, 실제로는 4계단 하락했는데 "-"(무변동)로
   표시되는 사례가 실제 로그로 확인됨. 원인은 frmrRnkn이 "우리가 마지막
   으로 수집한 시점" 기준이 아니라 교보 서버 자체의 내부 갱신 주기
   기준이라, GitHub Actions의 schedule 트리거 지연으로 우리 수집 간격이
   불규칙해질 때(예: 45~76분처럼 정확히 1시간이 아닐 때) 두 값이 서로
   다른 시점을 비교한 것이 되어 어긋나는 것으로 확인됐습니다. 우리 자신의
   직전 스냅샷과 비교하면 수집 간격이 얼마나 불규칙하든 "우리가 마지막
   으로 본 시점 대비"로 항상 정확합니다(예스24/알라딘이 이미 이 방식으로
   100% 정확했던 것과 동일한 이유).

기존 weekly/분야별 시스템과의 분리(변경 없음):
- rankings / collection_runs / books 테이블에는 전혀 쓰지 않고,
  realtime_rankings / realtime_collection_runs 테이블에만 저장합니다.
- test_save_kyobo_category.py, categories.py, collect.yml(매일 06시 정기
  수집), 예스24/알라딘 실시간 수집기는 전혀 건드리지 않습니다.
- realtime_rankings/realtime_collection_runs 저장 구조(컬럼 구성, insert
  방식)는 기존과 동일하게 유지합니다.

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

from test_save_kyobo import USER_AGENT, fetch_best_seller_page, item_to_book

BOOKSTORE = "교보문고"
LIST_URL = "https://store.kyobobook.co.kr/bestseller/realtime"
TARGET_COUNT = 100  # diagnose_kyobo_realtime_api.py로 확인된 total=100, page=1~5로 전체 커버


# 도서로 인정하는 saleCmdtDvsnCode 값. diagnose_kyobo_nonbook_fields.py로
# GitHub Actions에서 실제 확인한 근거:
# - 실시간 TOP100 정상 도서(물리책) 98/100건이 saleCmdtDvsnCode='KOR',
#   나머지 2건은 'EBK'(전자책)였고 둘 다 saleCmdtClstName이 실제 도서
#   장르명(또는 그에 준하는 값)이었음.
# - 실제로 TOP100에 섞여 들어온 것으로 확인된 비도서 굿즈("The Scent of
#   Page : 차량용 방향제(개선판)")를 교보 검색 결과 HTML을 통해 상세페이지로
#   찾아가 확인한 saleCmdtDvsnCode 값은 'PBC'로, KOR/EBK와 명확히 다름
#   (saleCmdtGrpDvsnCode는 도서와 동일하게 'SGK'라서 구분 기준으로 쓸 수
#   없었음). 같이 확인된 "GOGO [정규 3집]"(음반)은 상품 상세 URL 도메인
#   자체가 product.kyobobook.co.kr가 아니라 hottracks.kyobobook.co.kr로
#   완전히 별개 시스템이었음 - 도서와 saleCmdtDvsnCode가 같을 이유가 없음.
BOOK_SALE_CMDT_DVSN_CODES = {"KOR", "EBK"}


def load_realtime_list(page):
    """page=1~5(per=20)를 순서대로 열어 실시간 TOP100 전체를 모읍니다
    (diagnose_kyobo_realtime_api.py로 page당 서로 다른 20건씩 반환되는 것을
    실제 확인함 - 주간 load_top100_list와 동일한 페이지네이션 구조).

    saleCmdtDvsnCode가 KOR/EBK가 아닌 항목(디퓨저/방향제/음반 등 비도서
    굿즈)은 제외합니다. diagnose_kyobo_realtime_api.py로 page=6/7이 빈
    응답임을 이미 확인했으므로(사이트 자체가 TOP100 너머의 순위 데이터를
    제공하지 않음), 제외된 만큼 다음 순위로 백필할 방법이 없습니다 - 그래서
    최종 저장 건수가 100건보다 적어질 수 있습니다. prstRnkn(원래 순위)은
    재넘버링하지 않고 그대로 유지합니다(예: 45위가 비도서로 제외되면 46위는
    그대로 46위)."""
    books = []
    excluded_count = 0
    pages_needed = -(-TARGET_COUNT // 20)  # TARGET_COUNT=100 -> 5페이지

    for page_num in range(1, pages_needed + 1):
        page_url = LIST_URL if page_num == 1 else f"{LIST_URL}?page={page_num}"
        print(f"{page_num}페이지 로딩 중... ({page_url})")
        try:
            items = fetch_best_seller_page(page, page_url)
        except Exception as e:
            print(f"   진단: {page_num}페이지 조회 실패: {e}. 여기서 중단합니다.")
            break

        page_books = []
        for item in items:
            if not item.get("prstRnkn"):
                continue
            if item.get("saleCmdtDvsnCode") not in BOOK_SALE_CMDT_DVSN_CODES:
                excluded_count += 1
                print(
                    f"   -> 비도서로 판단해 제외: {item.get('prstRnkn')}위 "
                    f"'{item.get('cmdtName')}' (saleCmdtDvsnCode="
                    f"{item.get('saleCmdtDvsnCode')!r})"
                )
                continue
            page_books.append(item_to_book(item))

        books.extend(page_books)
        print(f"   -> {page_num}페이지에서 {len(page_books)}권 추가 (누적 {len(books)}권)")

        if not page_books and not items:
            print(f"   진단: {page_num}페이지에서 항목을 하나도 받지 못했습니다. 여기서 중단합니다.")
            break

    if excluded_count:
        print(f"\n비도서로 판단해 제외한 항목 {excluded_count}건 (백필 불가 - page=6/7이 빈 응답임을 사전 확인함).")
    if len(books) < TARGET_COUNT:
        print(f"진단: 목표({TARGET_COUNT}권)를 채우지 못했습니다({len(books)}권). 비도서 제외 및/또는 페이지 조회 실패가 원인일 수 있습니다.")

    books.sort(key=lambda b: b["rank"])
    return books


def get_previous_realtime_ranks(client):
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

        print(f"\n목록 수집 성공: {len(books)}권.\n")
    except Exception as e:
        error_message = str(e)
        print(f"\n교보문고 실시간 수집이 완전히 실패했습니다: {error_message}")

    # item_to_book()이 채워준 frmrRnkn 기반 rank_change(교보 API 자체 값)를
    # 여기서 우리 자신의 직전 스냅샷 비교값으로 덮어씁니다 - 예스24/알라딘과
    # 동일한 방식으로, 수집 간격이 불규칙해도 항상 "우리가 마지막으로 본
    # 시점 대비"로 정확하게 계산되도록 합니다.
    for book in books:
        isbn13 = book.get("isbn13")
        if isbn13 and isbn13 in prev_ranks:
            book["rank_change"] = prev_ranks[isbn13] - book["rank"]
        else:
            book["rank_change"] = None

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

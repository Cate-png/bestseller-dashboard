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

2. rank_change 우선순위 (2026-08-24 조사 이후 변경):
   1순위) 교보 API 원본의 prstRnkn(현재 순위)/frmrRnkn(이전 순위)이 유효한
   값이면 그 값을 그대로 씁니다. item_to_book()이 이미 frmrRnkn - prstRnkn
   으로 계산해둔 값을 그대로 가져다 쓸 뿐, 이 스크립트가 "교보 사이트가
   화면에 표시하는 값"을 별도로 재계산하지는 않습니다(애초에 교보 실시간
   페이지 자체에 등락을 보여주는 UI 요소가 없다는 것도 실측으로 확인함 -
   prstRnkn/frmrRnkn은 API 전용 값).
   2순위) frmrRnkn이 0/None(신규 진입 신호) 등 유효하지 않은 값이면, 예스24/
   알라딘 실시간 수집기와 동일하게 realtime_rankings에 저장해둔 우리 자신의
   직전 스냅샷을 (isbn13, url) 기준으로 찾아 비교해서 계산합니다
   (get_previous_realtime_ranks) - 이 경우에만 fallback으로 사용합니다.

   이렇게 우선순위를 둔 이유: 예전엔 frmrRnkn을 무조건 그대로 썼는데, 실제
   수집 로그 10회분을 ISBN13 기준으로 교차 대조한 결과 예스24/알라딘은
   100% 정확한 반면 교보만 6.3%(207쌍 중 13건) 불일치가 확인돼 자체 스냅샷
   비교 방식으로 한 번 전환했던 이력이 있습니다(원인: frmrRnkn은 "우리가
   마지막으로 수집한 시점" 기준이 아니라 교보 서버 자체의 내부 갱신 주기
   기준이라, GitHub Actions 트리거 지연으로 수집 간격이 불규칙해지면 두
   값이 서로 다른 시점을 비교한 게 되어 어긋남). 하지만 사용자 요청으로
   "서점 원본값 우선, 없을 때만 fallback"으로 다시 전환합니다 - frmrRnkn이
   유효한 대다수 케이스에는 그대로 쓰고, 0/None처럼 교보 스스로도 신뢰할
   근거가 없는 경우에만 우리 자신의 직전 스냅샷으로 보완합니다.

기존 weekly/분야별 시스템과의 분리(변경 없음):
- rankings / collection_runs / books 테이블에는 전혀 쓰지 않고,
  realtime_rankings / realtime_collection_runs 테이블에만 저장합니다.
- test_save_kyobo_category.py, categories.py, collect.yml(매일 06시 정기
  수집), 예스24/알라딘 실시간 수집기는 전혀 건드리지 않습니다.

2026-08-25(정책 변경): saleCmdtDvsnCode 기준 비도서 판별(디퓨저/방향제/
음반 등)로 순위권에서 아예 제외하던 것을 그만뒀습니다. 대시보드가
서점의 전체 트렌드를 보여주는 용도이므로 비도서도 유의미한 신호로
보고, item_type 컬럼(book/non_book)에 판별 결과만 남겨서 화면에서
시각적으로만(회색) 구분합니다. realtime_rankings/realtime_collection_runs
의 다른 저장 구조(컬럼 구성, insert 방식)는 item_type 추가 외에는
기존과 동일합니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import sys
from datetime import datetime, timedelta, timezone

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
    굿즈)도 2026-08-25부터 더 이상 순위권에서 제외하지 않습니다(정책
    변경 - 모듈 docstring 참고). item_to_book()이 만든 book dict에
    item_type만("book" 또는 "non_book") 추가로 표시해서 화면에서 회색
    처리할 수 있게 합니다. prstRnkn(원래 순위)은 그대로 씁니다."""
    books = []
    non_book_count = 0
    # 진단 전용(DB 저장 안 함): 교보 API가 각 항목에 붙이는 ymw(YYYYMMDDHH,
    # 교보 자신이 판단하는 "이 데이터가 속한 시간대") 값을 수집합니다.
    # resolvedAt(=collected_at, 우리 스크립트 시작 시각)과 이 ymw가 실제로
    # 어떻게 어긋나는지 다음 회차부터 로그로 대조하기 위한 용도입니다.
    ymw_values = set()
    pages_needed = -(-TARGET_COUNT // 20)  # TARGET_COUNT=100 -> 5페이지

    for page_num in range(1, pages_needed + 1):
        page_url = LIST_URL if page_num == 1 else f"{LIST_URL}?page={page_num}"
        print(f"{page_num}페이지 로딩 중... ({page_url})")
        try:
            items = fetch_best_seller_page(page, page_url)
        except Exception as e:
            print(f"   진단: {page_num}페이지 조회 실패: {e}. 여기서 중단합니다.")
            break

        page_ymw = {item.get("ymw") for item in items if item.get("ymw")}
        ymw_values |= page_ymw
        if page_ymw:
            print(f"   [진단] {page_num}페이지 항목들의 ymw(교보 기준 시간대): {sorted(page_ymw)}")

        page_books = []
        for item in items:
            if not item.get("prstRnkn"):
                continue
            book = item_to_book(item)
            if item.get("saleCmdtDvsnCode") not in BOOK_SALE_CMDT_DVSN_CODES:
                non_book_count += 1
                book["item_type"] = "non_book"
                print(
                    f"   -> 비도서로 판단(포함): {item.get('prstRnkn')}위 "
                    f"'{item.get('cmdtName')}' (saleCmdtDvsnCode="
                    f"{item.get('saleCmdtDvsnCode')!r})"
                )
            else:
                book["item_type"] = "book"
            page_books.append(book)

        books.extend(page_books)
        print(f"   -> {page_num}페이지에서 {len(page_books)}권 추가 (누적 {len(books)}권)")

        if not page_books and not items:
            print(f"   진단: {page_num}페이지에서 항목을 하나도 받지 못했습니다. 여기서 중단합니다.")
            break

    if non_book_count:
        print(f"\n비도서로 판단한 항목 {non_book_count}건 포함(제외하지 않음).")
    if len(books) < TARGET_COUNT:
        print(f"진단: 목표({TARGET_COUNT}권)를 채우지 못했습니다({len(books)}권). 페이지 조회 실패가 원인일 수 있습니다.")

    books.sort(key=lambda b: b["rank"])

    # 2026-08-26(실측 확인): 교보 API의 prstRnkn 자체에 원래부터 이가 빠져
    # 있습니다(예: 9위 다음이 11위, 10위가 아예 없음 - 매 회차 몇 군데씩
    # 발생). 교보문고 자기 사이트도 이 값을 그대로 믿지 않고 목록에 나온
    # 순서대로 1,2,3...으로 다시 매겨서 보여주기 때문에 이용자 눈에는 빈
    # 자리가 안 보이는데, 우리는 prstRnkn을 그대로 book["rank"]에 저장해서
    # 화면(대시보드)에 "7위가 없다"처럼 구멍이 그대로 드러났습니다.
    # rank_change는 위 for-loop에서 이미 원본 prstRnkn/frmrRnkn 값으로
    # 계산이 끝난 뒤라 아래에서 rank를 다시 매겨도 영향이 없습니다 - 정렬
    # 순서(=원본 순위 순서)만 그대로 유지한 채 화면 표시용 순위만
    # 1..N으로 재부여합니다(교보 사이트가 실제로 보여주는 순위와 동일한
    # 방식).
    for display_rank, book in enumerate(books, start=1):
        book["rank"] = display_rank

    # 진단 전용: 함수 속성에만 남겨 main()에서 읽게 합니다. 기존 반환값(books)
    # 모양이나 호출부 시그니처는 그대로 유지하기 위한 방식입니다.
    load_realtime_list.last_ymw_values = ymw_values
    return books


def get_previous_realtime_ranks(client):
    """직전 회차의 (isbn13, url) -> rank 매핑을 돌려줍니다.

    isbn13만으로 매핑하면 안 됩니다 - 교보문고는 같은 책의 종이책/전자책이
    서로 다른 상품(URL, 순위)인데도 ISBN13이 동일한 경우가 실제로 있어서,
    isbn13만 키로 쓰면 두 상품이 한 딕셔너리 키에서 충돌해 서로의 순위를
    덮어씁니다(실측: "어떻게 살아낼 것인가" 종이책 3위/전자책 33위가 isbn13
    하나로 겹치면서, 종이책 2위 등락이 실제로는 ↑1인데 ↑31로, 전자책은
    반대로 뒤섞여 계산된 사례). url은 상품(에디션) 단위로 고유하므로
    (isbn13, url) 조합을 키로 써서 같은 ISBN이라도 다른 상품이면 각자
    정확히 비교되도록 합니다.
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

        # 진단 전용 로그(DB 저장 안 함): resolvedAt으로 쓰이는 collected_at
        # (우리 스크립트 시작 시각)과 교보 API 자체가 붙인 ymw(교보가 판단하는
        # "기준 시간대")를 나란히 남겨, 다음 회차부터 둘이 실제로 얼마나
        # 어긋나는지 로그로 대조할 수 있게 합니다.
        ymw_values = getattr(load_realtime_list, "last_ymw_values", set())
        collected_at_kst = (
            datetime.fromisoformat(collected_at) + timedelta(hours=9)
        ).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[진단] collected_at(UTC)={collected_at} (KST {collected_at_kst}) "
            f"vs 교보 ymw(기준 시간대)={sorted(ymw_values) if ymw_values else '(관측 안 됨)'}"
        )
    except Exception as e:
        error_message = str(e)
        print(f"\n교보문고 실시간 수집이 완전히 실패했습니다: {error_message}")

    # item_to_book()이 이미 교보 API 원본(frmrRnkn - prstRnkn)으로 채워둔
    # rank_change가 유효하면(=frmrRnkn이 0/None이 아니어서 None이 아니면)
    # 그 값을 그대로 씁니다. frmrRnkn이 0/None이라 원본값이 없을 때만(=
    # book["rank_change"]가 None일 때만) 예스24/알라딘과 동일한 방식으로
    # 우리 자신의 직전 스냅샷 비교값으로 보완(fallback)합니다.
    fallback_used = 0
    origin_used = 0
    for book in books:
        if book["rank_change"] is not None:
            origin_used += 1
            continue
        isbn13 = book.get("isbn13")
        key = (isbn13, book.get("url"))
        if isbn13 and key in prev_ranks:
            book["rank_change"] = prev_ranks[key] - book["rank"]
            fallback_used += 1
        else:
            book["rank_change"] = None
    print(
        f"rank_change 계산: 교보 원본(prstRnkn/frmrRnkn) 사용 {origin_used}건, "
        f"우리 자신의 직전 스냅샷으로 fallback {fallback_used}건, "
        f"신규 진입(원본/자체 스냅샷 모두 없음) {len(books) - origin_used - fallback_used}건"
    )

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
    print(f"교보문고 실시간 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"수집 권수: {len(books)}")
    print(f"realtime_rankings 저장 권수: {rankings_saved}")
    print("=" * 80)
    print("실시간 TOP (순위 | 도서명 | 저자 | 출판사 | ISBN13 | 등락 | 유형)")
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
            f"{book['publisher']} | {book.get('isbn13') or '(없음)'} | {change_str} | "
            f"{book.get('item_type')}"
        )


if __name__ == "__main__":
    main()

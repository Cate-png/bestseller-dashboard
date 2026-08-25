"""알라딘 "지금 베스트"(실시간에 가장 가까운 랭킹) 수집 -> Supabase
realtime_rankings 저장.

기존 종합 주간 스크립트(test_save_aladin.py)에서 실제로 검증된 목록/상세
페이지 파싱 로직(goto_with_retry, parse_list, parse_detail)과 헤더/컨텍스트
설정(HEADERS, CONTEXT_KWARGS)을 그대로 import해서 재사용합니다.
test_save_aladin.py 자체는 전혀 수정하지 않습니다.

목록 페이지: https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=NowBest
("지금 베스트" - 알라딘에는 "실시간"이라는 이름의 페이지는 없고, 이 "지금
베스트"가 가장 가까운 개념입니다. 공식 갱신 주기는 공개 문서로 확인하지
못했으므로 "매시간 갱신된다"고 가정하지 않고, 매시간 수집은 하되 직전
스냅샷과 실제로 순위가 달라지는지를 아래 등락(rank_change) 로그로 계속
관찰합니다.)

diagnose_realtime.py로 GitHub Actions에서 실제로 확인한 내용:
- 이 URL은 1차 시도에서 CloudFront 403을 받았지만, 기존 goto_with_retry()로
  재시도하면 정상 로딩됩니다(기존 알라딘 스크래퍼가 이미 겪던 일시적 차단과
  동일한 패턴).
- 기존 selector(div.ss_book_box / a.bo3)가 그대로 매칭되고, 1페이지에 50건이
  잡힙니다.

diagnose_aladin_realtime_pagination.py로 추가 확인한 내용(page=1만 수집하던
탓에 최종 저장 건수가 46건에 그쳤던 원인 조사):
- 종합 주간 수집기(test_save_aladin.py)와 동일한 page=2&cnt=1000&SortOrder=1
  파라미터를 NowBest에도 그대로 적용하면 51위 이후 49건이 추가로 잡힙니다
  (1페이지 50건 + 2페이지 49건 = 99건). page=3 이상은 그 시점 기준 0건(빈
  응답)이었습니다.

유효 도서 100개 확보 로직(2번째 개선, 46건 -> 93건 다음 단계):
- 기존에는 "목록(최대 2페이지) 전체 수집 -> 상세페이지 전부 조회 -> 비도서/
  오디오북 필터링" 순서라서, 필터링 후 유효 도서가 100개에 못 미쳐도 추가
  페이지를 요청할 방법이 없었습니다(이미 목록 수집이 끝난 뒤였으므로).
- collect_valid_books()는 이 순서를 "페이지 1건 조회 -> 그 페이지만 상세
  조회 -> 필터링 -> 유효 도서 수 확인 -> 부족하면 다음 페이지" 순서로
  바꿔서, 유효 도서가 100개가 될 때까지, 또는 알라딘 원본 목록이 빈 페이지를
  반환할 때까지(원본 데이터 소진) 페이지를 계속 요청합니다. page=3 이상이
  실제로 몇 건을 주는지는 이 스크립트를 실행할 때마다 알라딘 사이트 상태에
  따라 달라질 수 있어 고정 페이지 수로 미리 자르지 않습니다.
- 원본 알라딘 순위(rank)는 parse_list()가 각 페이지의 start_rank(누적
  raw 건수 + 1)를 기준으로 매긴 값을 그대로 사용하고, 필터링 이후 다시
  1부터 번호를 매기지 않습니다(예: 1페이지에서 3건이 제외돼도 유효 도서의
  rank는 4, 5, 6이 아니라 원본 그대로인 4, 6, 7 등일 수 있음).
- 다만 알라딘 "지금 베스트" 자체가 페이지를 아무리 넘겨도 100건을
  제공하지 않을 수 있고(실측상 page=3 이상이 0건이었던 시점 기준으로는
  raw 최대 99건), 그중 비도서/오디오북이 섞여 있으므로 최종 저장 건수가
  100건에 못 미칠 수 있습니다 - 이 경우 원본 데이터 소진이 원인이며 수집
  로직의 결함이 아닙니다.
- 다만 "지금 베스트"에는 도서가 아닌 상품(문구류, 오디오북 세트 등)이 실제로
  섞여 있는 것을 확인했습니다:
  * '감쪽같은 수정 테이프 무소음' -> 상세페이지 isbn13이 'G000272432602'
    (알라딘 내부 굿즈 코드, 13자리 숫자 ISBN이 아님) -> "isbn13이 13자리
    숫자인지" 검사로 판별.
  * '[세트] 피를 마시는 새 오디오북' -> 상세페이지 isbn13이
    '9791170528227'(유효한 13자리 숫자)로, ISBN 검사만으로는 걸러지지
    않는 경계 케이스. 오디오북은 텍스트책이 아니므로 제목에 "오디오북"이
    포함되면 별도로 판별합니다.

2026-08-25(정책 변경): 위 판별 기준(is_real_book, 지금은
classify_item_type)으로 비도서를 실시간 순위권에서 아예 제외하던 것을
그만뒀습니다. 대시보드가 "도서 판매량"뿐 아니라 서점의 전체 트렌드를
보여주는 용도이므로 비도서도 유의미한 신호로 보고, 이제는 제외하지
않고 그대로 저장하되 item_type 컬럼(book/audiobook/non_book)에 판별
결과만 남겨서 화면에서 시각적으로만 구분합니다(회색 처리). 분야
분류(store_category, 이 스크립트에는 없음)와는 완전히 별개 개념이라
비도서를 "기타 분야"로 넣거나 하지 않습니다.

기존 weekly/분야별 시스템과의 분리:
- rankings / collection_runs / books 테이블에는 전혀 쓰지 않고,
  realtime_rankings / realtime_collection_runs 테이블에만 저장합니다.
- test_save_aladin.py, test_save_aladin_category.py, categories.py,
  collect.yml(매일 06시 정기 수집)은 전혀 건드리지 않습니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import sys
from datetime import datetime, timezone

try:
    from supabase import create_client
except ImportError:
    print("오류: supabase 라이브러리가 설치되어 있지 않습니다. (pip install supabase)")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

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
TARGET_COUNT = 100  # 확보하려는 목표 개수(비도서/오디오북도 포함해서 셈)
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4


def fetch_nowbest_list_page(page, page_num):
    params = {
        "BranchType": "1",  # 국내도서
        "BestType": "NowBest",  # "지금 베스트" - 실시간에 가장 가까운 랭킹
    }
    if page_num > 1:
        # 종합 주간 수집기(test_save_aladin.py)의 fetch_list_page와 동일한
        # 2페이지 이후 파라미터 - diagnose_aladin_realtime_pagination.py로
        # NowBest에도 그대로 적용됨을 실측 확인함.
        params["page"] = str(page_num)
        params["cnt"] = "1000"
        params["SortOrder"] = "1"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    return goto_with_retry(page, url)


def fetch_nowbest_page_books(page_num, start_rank):
    """이 페이지 하나만 담당하는 독립된 Playwright 세션을 열어 목록을
    가져옵니다. list-fetch 세션과 아래 enrich_with_details()의 세션을
    절대 중첩시키지 않기 위해(기존 코드도 항상 목록 수집 세션을 완전히
    닫은 뒤에만 상세조회 세션을 열었음), 페이지마다 새로 열고 닫습니다."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=HEADERS["User-Agent"], **CONTEXT_KWARGS)
            html = fetch_nowbest_list_page(page, page_num)
            return parse_list(html, start_rank)
        finally:
            browser.close()


def _fetch_one_detail(page, book):
    try:
        html = goto_with_retry(page, book["url"])
        detail = parse_detail(html)
    except Exception as e:
        print(f"   -> 상세 페이지 조회 실패, 이 항목은 제목/URL만 저장합니다: {e}")
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


def classify_item_type(book):
    """diagnose_realtime.py로 실측 확인된 판별 기준. 예전에는 이 결과로
    비도서를 순위권에서 아예 제외했지만, 이제는 제외하지 않고 상품
    유형만 분류해서 저장합니다(화면에서 회색으로 구분 표시하는 용도) -
    분야 분류(store_category)와는 완전히 별개입니다.

    - isbn13이 13자리 숫자가 아니면(알라딘 내부 굿즈 코드 등) "non_book".
    - isbn13은 유효해도 제목에 "오디오북"이 포함되면 "audiobook"
      (텍스트책이 아니므로).
    - 그 외는 "book"."""
    isbn13 = book.get("isbn13")
    if not isbn13 or not isbn13.isdigit() or len(isbn13) != 13:
        return "non_book"
    if "오디오북" in (book.get("title") or ""):
        return "audiobook"
    return "book"


def collect_valid_books(target_valid=TARGET_COUNT):
    """target_valid개(기본 100)를 모을 때까지, 또는 알라딘 원본 목록이
    빈 페이지를 반환할 때까지(원본 데이터 소진) 페이지를 계속 가져와
    상세 페이지까지 조회합니다. 비도서(오디오북/굿즈 등)도 더 이상
    제외하지 않고 그대로 포함하며, item_type만 분류해서 채웁니다.

    원본 알라딘 순위(rank)는 parse_list()가 각 페이지의 start_rank(누적
    raw 건수 + 1)를 기준으로 매긴 값을 그대로 사용합니다.

    반환값: (books, raw_count)
    """
    books = []
    cumulative_raw = 0
    page_num = 1

    while len(books) < target_valid:
        page_books = fetch_nowbest_page_books(page_num, cumulative_raw + 1)
        if not page_books:
            if page_num == 1:
                raise RuntimeError("지금 베스트 목록 페이지에서 도서를 하나도 추출하지 못했습니다.")
            print(f"   -> {page_num}페이지에서 항목을 받지 못했습니다(원본 데이터 소진). 여기서 종료합니다.")
            break

        cumulative_raw += len(page_books)
        print(f"   -> {page_num}페이지에서 raw {len(page_books)}건 추가 (누적 raw {cumulative_raw}건)")

        enrich_with_details(page_books)

        non_book_count = 0
        for book in page_books:
            book["item_type"] = classify_item_type(book)
            if book["item_type"] != "book":
                non_book_count += 1
            books.append(book)
        print(
            f"   -> {page_num}페이지 상세조회 완료: {len(page_books)}건 추가"
            f"(비도서 {non_book_count}건 포함, 누적 {len(books)}/{target_valid}건)"
        )

        page_num += 1

    return books[:target_valid], cumulative_raw


def get_previous_realtime_ranks(client):
    """직전 회차의 (isbn13, url) -> rank 매핑을 돌려줍니다.

    isbn13만으로 매핑하면 안 됩니다 - 종이책/전자책처럼 같은 ISBN13을 공유하는
    서로 다른 상품이 리스트에 함께 들어있으면(교보문고에서 실측 확인된 사례),
    isbn13만 키로 쓸 경우 두 상품이 한 딕셔너리 키에서 충돌해 서로의 순위를
    덮어써 등락이 크게 틀어집니다. url은 상품(에디션) 단위로 고유하므로
    (isbn13, url) 조합을 키로 써서 이런 충돌을 막습니다. 알라딘은 현재
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

    print("직전 알라딘 실시간 수집 결과 조회 중 (순위 변동 계산용)...")
    prev_ranks = get_previous_realtime_ranks(client)
    print(f"직전 스냅샷 도서 수: {len(prev_ranks)}권\n")

    collected_at = datetime.now(timezone.utc).isoformat()
    error_message = None
    books = []
    raw_count = 0

    try:
        print(
            f"알라딘 '지금 베스트' 목록/상세 수집 중 "
            f"({TARGET_COUNT}개 확보 또는 원본 소진까지 페이지 반복, 비도서도 포함)...\n"
        )
        books, raw_count = collect_valid_books()
        if not books:
            raise RuntimeError("도서를 하나도 수집하지 못했습니다.")
        non_book_count = sum(1 for b in books if b["item_type"] != "book")
        print(
            f"\n목록/상세 수집 완료: raw {raw_count}건 중 {len(books)}건 저장 "
            f"(비도서 {non_book_count}건 포함, 제외 없음).\n"
        )
    except Exception as e:
        error_message = str(e)
        books = []
        print(f"\n알라딘 실시간 수집이 완전히 실패했습니다: {error_message}")

    # 원본 알라딘 rank(parse_list가 페이지별 누적 위치로 매긴 값)를 그대로
    # 유지한 채 정렬만 합니다.
    books.sort(key=lambda b: b["rank"])

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
    print(f"\nrealtime_collection_runs 기록 완료. run_id={run_id}, status={status}")

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
    print(f"알라딘 실시간 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"원본(raw) 수집 건수: {raw_count}")
    print(f"수집 건수(비도서 포함): {len(books)}")
    print(f"realtime_rankings 저장 건수: {rankings_saved}")
    if books:
        print(f"저장된 항목 중 가장 큰 원본 rank: {max(b['rank'] for b in books)}")
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

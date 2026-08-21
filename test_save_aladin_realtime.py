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
- 기존 selector(div.ss_book_box / a.bo3)가 그대로 매칭되고, 50건이 잡힙니다.
- 다만 "지금 베스트"에는 도서가 아닌 상품(문구류, 오디오북 세트 등)이 실제로
  섞여 있는 것을 확인했습니다:
  * '감쪽같은 수정 테이프 무소음' -> 상세페이지 isbn13이 'G000272432602'
    (알라딘 내부 굿즈 코드, 13자리 숫자 ISBN이 아님) -> "isbn13이 13자리
    숫자인지" 검사로 걸러낼 수 있음을 실측으로 확인.
  * '[세트] 피를 마시는 새 오디오북' -> 상세페이지 isbn13이
    '9791170528227'(유효한 13자리 숫자)로, ISBN 검사만으로는 걸러지지
    않는 경계 케이스. 오디오북은 텍스트책이 아니므로 제목에 "오디오북"이
    포함되면 추가로 제외합니다.

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
TARGET_COUNT = 50  # diagnose_realtime.py로 확인된, 이 URL의 1페이지 노출 개수
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4


def fetch_nowbest_list_page(page):
    params = {
        "BranchType": "1",  # 국내도서
        "BestType": "NowBest",  # "지금 베스트" - 실시간에 가장 가까운 랭킹
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    return goto_with_retry(page, url)


def collect_nowbest(page):
    html = fetch_nowbest_list_page(page)
    books = parse_list(html, start_rank=1)
    if not books:
        raise RuntimeError("지금 베스트 목록 페이지에서 도서를 하나도 추출하지 못했습니다.")
    return books[:TARGET_COUNT]


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


def is_real_book(book):
    """diagnose_realtime.py로 실측 확인된 필터. isbn13이 진짜 13자리 숫자
    ISBN이 아니면(알라딘 내부 굿즈 코드 등) 도서가 아닌 것으로 보고 제외.
    ISBN은 있어도 오디오북(텍스트책이 아님)이면 마찬가지로 제외."""
    isbn13 = book.get("isbn13")
    if not isbn13 or not isbn13.isdigit() or len(isbn13) != 13:
        return False
    if "오디오북" in (book.get("title") or ""):
        return False
    return True


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

    print("직전 알라딘 실시간 수집 결과 조회 중 (순위 변동 계산용)...")
    prev_ranks = get_previous_realtime_ranks(client)
    print(f"직전 스냅샷 도서 수: {len(prev_ranks)}권\n")

    collected_at = datetime.now(timezone.utc).isoformat()
    error_message = None
    raw_books = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                raise RuntimeError(
                    f"브라우저 실행 실패: {e} "
                    "('playwright install chromium' 실행 여부 확인 필요)"
                )

            page = browser.new_page(user_agent=HEADERS["User-Agent"], **CONTEXT_KWARGS)
            print("알라딘 '지금 베스트' 목록 수집 중...")
            raw_books = collect_nowbest(page)
            browser.close()

        print(
            f"목록 수집 성공: {len(raw_books)}건. "
            f"상세 페이지를 동시성={DETAIL_CONCURRENCY}로 조회합니다.\n"
        )
        raw_books = enrich_with_details(raw_books)
    except Exception as e:
        error_message = str(e)
        print(f"\n알라딘 실시간 수집이 완전히 실패했습니다: {error_message}")

    # 도서가 아닌 항목(문구류, 오디오북 등)은 여기서 걸러내고, 남은 도서만
    # rank를 1부터 다시 매겨서 "실시간 도서 전용 순위"로 만듭니다.
    excluded = [b for b in raw_books if not is_real_book(b)]
    book_only = [b for b in raw_books if is_real_book(b)]
    book_only.sort(key=lambda b: b["rank"])
    for i, book in enumerate(book_only):
        book["rank"] = i + 1

    if excluded:
        print(f"\n도서가 아닌 것으로 판단해 제외한 항목 {len(excluded)}건:")
        for b in excluded:
            print(f"   - {b['title']} (isbn13={b.get('isbn13') or '(없음)'})")

    books = book_only

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
        }
        for book in books
    ]
    rankings_result = client.table("realtime_rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"realtime_rankings 저장 완료: {rankings_saved}건")

    print("\n" + "=" * 80)
    print(f"알라딘 실시간 수집 성공 여부: {status}")
    print(f"run_id: {run_id}")
    print(f"수집 권수(도서만): {len(books)}")
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

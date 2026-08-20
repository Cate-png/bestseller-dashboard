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

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import sys
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

try:
    from supabase import create_client
except ImportError:
    print("오류: supabase 라이브러리가 설치되어 있지 않습니다. (pip install supabase)")
    sys.exit(1)

BOOKSTORE = "알라딘"
CATEGORY = "종합"

LIST_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

DETAIL_REQUEST_DELAY = 2.0
TARGET_COUNT = 100


# ─────────────────────────────────────────────
# 아래 fetch_list_page / parse_list / fetch_detail_page / parse_detail 4개 함수는
# test_aladin_bestseller.py에서 실제로 검증된 로직을 그대로 가져온 것입니다.
# (parse_list에 페이지네이션을 위한 start_rank 인자만 추가했습니다.)
# ─────────────────────────────────────────────

def fetch_list_page(page_num: int) -> str:
    params = {
        "BestType": "Bestseller",
        "BranchType": 1,   # 국내도서
        "CID": 0,          # 0 = 종합(전체 분야)
    }
    if page_num > 1:
        params["page"] = page_num
        params["cnt"] = 1000
        params["SortOrder"] = 1
    resp = requests.get(LIST_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


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
        books.append({"rank": rank, "title": title, "url": url})
        rank += 1

    return books


def fetch_detail_page(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


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

    return {"author": ", ".join(authors), "publisher": publisher, "isbn13": isbn13}


# ─────────────────────────────────────────────
# 여기부터 이번에 새로 추가한 부분
# ─────────────────────────────────────────────

def collect_top100():
    """목록 2페이지(1~50, 51~100)를 가져와 TOP100 도서 목록(제목/URL/순위)을 만듭니다."""
    all_books = []
    for page_num, start_rank in ((1, 1), (2, 51)):
        html = fetch_list_page(page_num)
        books = parse_list(html, start_rank)
        if not books:
            raise RuntimeError(f"목록 페이지 {page_num}에서 도서를 하나도 추출하지 못했습니다.")
        all_books.extend(books)
    return all_books[:TARGET_COUNT]


def enrich_with_details(books):
    """각 도서의 상세 페이지를 방문해 저자/출판사/ISBN13을 채웁니다.
    개별 도서 조회가 실패해도 전체를 중단하지 않고, 그 도서만 빈 정보로 남깁니다."""
    total = len(books)
    for i, book in enumerate(books):
        print(f"[{book['rank']}/{total}] 상세 조회 중: {book['title']}")
        try:
            html = fetch_detail_page(book["url"])
            detail = parse_detail(html)
        except Exception as e:
            print(f"   -> 상세 페이지 조회 실패, 이 도서는 제목/URL만 저장합니다: {e}")
            detail = {"author": "", "publisher": "", "isbn13": ""}

        book["author"] = detail["author"]
        book["publisher"] = detail["publisher"]
        book["isbn13"] = detail["isbn13"] or None

        if i < total - 1:
            time.sleep(DETAIL_REQUEST_DELAY)

    return books


def get_previous_ranks(client):
    """가장 최근 성공한 알라딘 수집(run)의 isbn13 -> rank 매핑을 가져옵니다.
    이전 수집이 없으면 빈 dict를 반환합니다 (전부 신규진입 처리)."""
    prev_run = (
        client.table("collection_runs")
        .select("id")
        .eq("bookstore", BOOKSTORE)
        .eq("status", "success")
        .order("run_at", desc=True)
        .limit(1)
        .execute()
    )
    if not prev_run.data:
        return {}

    prev_run_id = prev_run.data[0]["id"]
    prev_rankings = (
        client.table("rankings")
        .select("isbn13, rank")
        .eq("run_id", prev_run_id)
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
        print("알라딘 TOP100 목록 수집 중...")
        books = collect_top100()
        print(f"목록 수집 성공: {len(books)}권\n")
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
        }
        for book in books
    ]
    rankings_result = client.table("rankings").insert(rankings_payload).execute()
    rankings_saved = len(rankings_result.data)
    print(f"rankings 테이블 저장 완료: {rankings_saved}건")

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

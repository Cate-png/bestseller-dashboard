"""
교보문고 국내도서 종합(주간) 베스트셀러 TOP100 수집 -> Supabase 저장 스크립트

내부 JSON API 기반으로 전환 (기존 HTML 스크래핑 + 상세페이지 100개 순회 방식 폐기):
- 목록 페이지(store.kyobobook.co.kr/bestseller/total/weekly)가 실제로는
  https://store.kyobobook.co.kr/api/gw/best/best-seller/total?page=N&per=20&period=002&bsslBksClstCode=A
  라는 내부 JSON API로 데이터를 채우고 있다는 것을 GitHub Actions에서 실제
  네트워크 응답을 캡처해서 확인했습니다(diagnose_rank_change_source.py /
  diagnose_kyobo_api.py, 레포에는 미포함). 이 API 응답 항목에 다음 필드가
  전부 들어있어 상세페이지를 따로 방문할 필요가 없습니다:
    - prstRnkn: 현재 순위
    - frmrRnkn: 이전 순위 (0이면 신규 진입 - TOP100 실측 100건 중 9건에서
      0으로 확인됨, null은 한 번도 나오지 않음)
    - cmdtCode: ISBN13 (실측 100건 전부 비어있지 않음)
    - cmdtName / chrcName / pbcmName: 제목 / 저자 / 출판사
    - saleCmdtid: 상세페이지 URL 생성에 쓰는 상품 ID (예: S000220308313)

  plain requests로 이 API를 직접 호출하면 403("API Gateway 라이센스
  키가 없습니다")으로 막힌다는 것도 실제로 확인했습니다. 그래서 임의의
  키/헤더를 추측해서 흉내내지 않고, 기존과 동일하게 Playwright로 실제
  페이지를 열어(그러면 브라우저가 정상적으로 필요한 걸 붙여서 요청하므로)
  그 안에서 발생하는 이 API 응답만 가로채는 방식을 그대로 씁니다.

  page=1~5(per=20)가 실제로 순위 1~20, 21~40, ..., 81~100을 순서대로
  채워주는 것도 Playwright로 직접 확인했습니다(기존 HTML 스크래핑
  버전과 동일한 페이지네이션 구조).

rank_change 계산: frmrRnkn - prstRnkn (frmrRnkn이 0이면 신규 진입으로 보고
None). Supabase 저장 구조(rankings/books/collection_runs), category="종합"
구분, match_status 로직, 프론트엔드 표시 규칙은 전혀 바꾸지 않았습니다.

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

BOOKSTORE = "교보문고"
CATEGORY = "종합"

LIST_URL = "https://store.kyobobook.co.kr/bestseller/total/weekly"
TARGET_COUNT = 100

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# ─────────────────────────────────────────────
# 아래 fetch_detail / GET_HREF_JS / ISBN13_PATTERN / IMG_SELECTOR는 이
# 스크립트의 종합 TOP100 수집(main 이하)에서는 더 이상 쓰지 않습니다(내부 API로
# 전환했으므로 상세페이지 방문 자체가 불필요해짐). test_save_kyobo_realtime.py도
# 같은 내부 API 기반 방식으로 전환되면서 더는 이 4개를 import하지 않아,
# 현재 저장소 안에서 이 4개를 쓰는 곳은 없습니다. 다만 상세페이지를 직접
# 파싱해야 하는 경우를 대비해 참고용으로 남겨둡니다.
# ─────────────────────────────────────────────

GET_HREF_JS = "(img) => img.closest('a') ? img.closest('a').getAttribute('href') : null"
ISBN13_PATTERN = re.compile(r"/pdt/(\d{13})\.")

IMG_SELECTOR = "a[href*='product.kyobobook.co.kr/detail/'] img"


def fetch_detail(page, url: str):
    page.goto(url, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    html = page.content()

    isbn13 = ""
    m = ISBN13_PATTERN.search(html)
    if m:
        isbn13 = m.group(1)

    author = ""
    author_meta = page.locator("meta[property='eg:brandName']")
    if author_meta.count() > 0:
        author = (author_meta.first.get_attribute("content") or "").strip()

    publisher = ""
    publisher_link = page.locator("a[href*='pbcmCode=']")
    if publisher_link.count() > 0:
        publisher = publisher_link.first.inner_text().strip()

    return {"isbn13": isbn13 or None, "author": author, "publisher": publisher}


def item_to_book(item):
    """best-seller API 응답의 도서 1건(JSON dict)을 기존 스크립트가 쓰던
    book dict 모양으로 변환합니다. rank_change는 API가 주는 이전 순위
    (frmrRnkn)와 현재 순위(prstRnkn)를 직접 비교해서 계산합니다 - 더 이상
    우리가 저장해둔 직전 Supabase 스냅샷과 비교하지 않습니다."""
    prst_rank = item.get("prstRnkn")
    frmr_rank = item.get("frmrRnkn")
    isbn13 = item.get("cmdtCode") or None
    sale_cmdtid = item.get("saleCmdtid") or ""

    if frmr_rank and frmr_rank > 0:
        rank_change = frmr_rank - prst_rank
    else:
        # frmrRnkn == 0: 실측으로 확인된 "신규 진입" 표시값(null은 관측되지 않음)
        rank_change = None

    return {
        "rank": prst_rank,
        "title": (item.get("cmdtName") or "").strip(),
        "author": (item.get("chrcName") or "").strip(),
        "publisher": (item.get("pbcmName") or "").strip(),
        "isbn13": isbn13,
        "url": f"https://product.kyobobook.co.kr/detail/{sale_cmdtid}" if sale_cmdtid else "",
        "rank_change": rank_change,
        "match_status": "matched" if isbn13 else "no_isbn",
    }


def fetch_best_seller_page(page, url):
    """지정한 목록 페이지 URL을 Playwright로 열고, 그 과정에서 발생하는
    best-seller API JSON 응답을 가로채 반환합니다. API를 직접 호출하지 않고
    실제 페이지 탐색을 통해서만 데이터를 받습니다(직접 호출은 403으로 막힘)."""
    captured = []

    def on_response(response):
        try:
            resp_url = response.url
            if "api/gw/best/best-seller/" not in resp_url:
                return
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            captured.append(response.json())
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(1500)
    finally:
        page.remove_listener("response", on_response)

    if not captured:
        raise RuntimeError(f"best-seller API 응답을 캡처하지 못했습니다: {url}")

    body = captured[-1]
    return body.get("data", {}).get("bestSeller", []) or []


def load_top100_list(page):
    """page=1 ~ page=5(per=20)를 순서대로 열어 페이지당 20권씩, 총 최대
    100권을 모읍니다(page=1~5가 실제로 순위 1~20, ..., 81~100을 채워주는
    것을 Playwright로 실제 확인함)."""
    books = []
    pages_needed = -(-TARGET_COUNT // 20)  # TARGET_COUNT=100 -> 5페이지

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


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

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
            books = load_top100_list(page)
            browser.close()

        if not books:
            raise RuntimeError("목록에서 도서를 하나도 추출하지 못했습니다.")
    except Exception as e:
        error_message = str(e)
        print(f"\n교보문고 수집이 완전히 실패했습니다: {error_message}")

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
        print("저장할 도서 데이터가 없어 books/rankings 저장은 건너뜁니다.")
        sys.exit(1)

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
    print(f"rankings 테이블 저장 완료: {rankings_saved}건")

    # rankings 저장이 실제로 끝난 직후의 시각을 collection_runs.run_at에 다시
    # 기록합니다. run_at은 원래 이 run 레코드를 만들 때 DB 기본값(now())으로
    # 채워지는데, 그 시점은 books/rankings 저장 이전이라 "실제 저장 완료 시각"과는
    # 다릅니다. collected_at(각 rankings 행의 회차 식별자로 계속 쓰이는 값)은
    # 건드리지 않고, 화면 표시용으로만 쓰이는 run_at만 갱신합니다.
    saved_at = datetime.now(timezone.utc).isoformat()
    client.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id).execute()
    print(f"collection_runs.run_at을 실제 저장 완료 시각으로 갱신: {saved_at}")

    print("\n" + "=" * 80)
    print(f"교보문고 수집 성공 여부: {status}")
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

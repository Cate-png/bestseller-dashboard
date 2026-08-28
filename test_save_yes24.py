import os
from datetime import datetime, timezone

import requests
from supabase import create_client

from concurrency_utils import enrich_details_concurrently
from supabase_retry import execute_with_retry

YES24_URL = "https://apis.yes24.com/v1/category/bestseller"
CATEGORY_ID = "001"
PAGE_SIZE = 100

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
DETAIL_REQUEST_DELAY = 2.0
DETAIL_CONCURRENCY = 4


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} 환경변수가 없습니다.")
    return value


def fetch_yes24():
    api_key = require_env("YES24_API_KEY")

    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }
    params = {
        "categoryId": CATEGORY_ID,
        "page": 1,
        "pageSize": PAGE_SIZE,
    }

    print("예스24 TOP100 수집 중...")
    response = requests.get(
        YES24_URL,
        headers=headers,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("success") is False:
        raise RuntimeError(
            f"예스24 API 실패: {payload.get('errorCode')} / {payload.get('message')}"
        )

    data = payload.get("data") or {}
    items = data.get("items") or []

    if not items:
        raise RuntimeError("예스24 API 응답에 도서 데이터가 없습니다.")

    print(f"예스24 수집 성공: {len(items)}권")
    return items


def fetch_store_category(page, url):
    """예스24 상품 상세페이지에서 분야 breadcrumb(a.yLocaDepth)의 2번째
    값을 가져옵니다. 실측 확인: a.yLocaDepth 링크들이 순서대로
    ["국내도서", 대분류, 중분류, ...]를 담고 있습니다(예: 세네카 도서 ->
    ["국내도서","인문","인문/교양","교양으로 읽는 ..."], 처음 읽는 그리스
    로마 신화 -> ["국내도서","어린이","1-2학년",...]). index 1(대분류)을
    씁니다 - 교보 saleCmdtClstName, 알라딘 breadcrumb과 같은 granularity
    (대분류 1단계)로 맞추기 위함입니다."""
    page.goto(url, timeout=30000)
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(1000)

    links = page.locator("a.yLocaDepth")
    if links.count() >= 2:
        text = links.nth(1).inner_text().strip()
        return text or None
    return None


def _fetch_one_category(page, probe):
    try:
        probe["store_category"] = fetch_store_category(page, probe["url"])
    except Exception as e:
        print(f"   -> 상세 페이지 조회 실패, 분야 정보 없이 저장합니다: {e}")
        probe["store_category"] = None


def fetch_store_categories(items):
    """종합 TOP100 API 응답(items)의 각 도서 상세페이지(link)를 방문해
    분야를 가져와 {url: store_category} 매핑으로 돌려줍니다.

    API 응답의 isbn13/author/publisher는 이미 확정된 값이라 이 조회에
    전혀 관여시키지 않습니다 - rank/title/url만 담은 별도 dict(probe)로
    넘겨서, enrich_details_concurrently 끝에 있는 isbn13 기준 중복 정리
    로직(_clear_stale_duplicate_isbns)이 이 probe들에는 항상 적용되지
    않게(isbn13 키 자체가 없으므로 no-op) 만들었습니다 - 서로 다른 두
    도서가 같은 isbn13(종이책/전자책 등)을 공유하는 경우에도, API가 이미
    준 정상 isbn13/author/publisher가 이 분야 조회 때문에 잘못 지워지는
    일이 없습니다.
    """
    probes = []
    for item in items:
        url = str(item.get("link") or "").strip()
        if not url:
            continue
        probes.append(
            {
                "rank": item.get("sortOrder"),
                "title": str(item.get("title") or "").strip(),
                "url": url,
            }
        )

    probes = enrich_details_concurrently(
        probes,
        fetch_one=_fetch_one_category,
        user_agent=USER_AGENT,
        concurrency=DETAIL_CONCURRENCY,
        request_delay=DETAIL_REQUEST_DELAY,
    )
    return {p["url"]: p.get("store_category") for p in probes}


def main():
    yes24_key = require_env("YES24_API_KEY")
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_KEY")

    # 키 자체는 절대 출력하지 않습니다.
    print("Supabase 클라이언트 생성 중...")
    supabase = create_client(supabase_url, supabase_key)

    items = fetch_yes24()
    collected_at = datetime.now(timezone.utc).isoformat()

    # 종합 TOP100의 원본(예스24 자체) 분야를 상세페이지에서 가져옵니다.
    # 실패해도(예: Playwright/Chromium 문제) 순위 저장 자체는 계속
    # 진행합니다 - store_category 없이 저장될 뿐입니다(기존 핵심 기능인
    # 순위 저장을 이 새 기능 때문에 통째로 실패시키지 않기 위함).
    try:
        print(
            f"예스24 종합 TOP100 분야 정보 조회 중 "
            f"(상세페이지 동시성={DETAIL_CONCURRENCY})..."
        )
        category_by_url = fetch_store_categories(items)
        print(f"분야 정보 조회 완료: {sum(1 for v in category_by_url.values() if v)}권\n")
    except Exception as e:
        print(f"분야 정보 조회 실패, store_category 없이 저장합니다: {e}\n")
        category_by_url = {}

    # 1. 이번 수집 실행(run) 기록
    run_result = execute_with_retry(
        supabase.table("collection_runs")
        .insert(
            {
                "run_at": collected_at,
                "bookstore": "예스24",
                "status": "success",
                "item_count": len(items),
            }
        )
    )

    if not run_result.data:
        raise RuntimeError("collection_runs 저장에 실패했습니다.")

    run_id = run_result.data[0]["id"]
    print(f"collection_runs 저장 성공: run_id={run_id}")

    # 2. 도서 마스터 저장
    book_rows = []
    for item in items:
        isbn13 = str(item.get("isbn13") or "").strip()
        if not isbn13:
            continue

        book_rows.append(
            {
                "isbn13": isbn13,
                "title": str(item.get("title") or "").strip(),
                "author": str(item.get("author") or "").strip() or None,
                "publisher": str(item.get("publisher") or "").strip() or None,
                "updated_at": collected_at,
            }
        )

    if book_rows:
        execute_with_retry(
            supabase.table("books")
            .upsert(book_rows, on_conflict="isbn13")
        )

    print(f"books 저장/갱신 성공: {len(book_rows)}권")

    # 3. 순위 스냅샷 저장
    ranking_rows = []

    for item in items:
        rank = item.get("sortOrder")
        title = str(item.get("title") or "").strip()
        author = str(item.get("author") or "").strip() or None
        publisher = str(item.get("publisher") or "").strip() or None
        isbn13 = str(item.get("isbn13") or "").strip() or None
        url = str(item.get("link") or "").strip() or None

        # upDown은 예스24가 제공하는 등락 값.
        # 데이터가 없거나 숫자가 아니면 NULL로 저장.
        raw_change = item.get("upDown")
        try:
            rank_change = int(raw_change) if raw_change is not None else None
        except (TypeError, ValueError):
            rank_change = None

        ranking_rows.append(
            {
                "run_id": run_id,
                "collected_at": collected_at,
                "bookstore": "예스24",
                "category": "종합",
                "rank": int(rank),
                "title": title,
                "author": author,
                "publisher": publisher,
                "isbn13": isbn13,
                "url": url,
                "match_status": "matched" if isbn13 else "no_isbn",
                "rank_change": rank_change,
                "store_category": category_by_url.get(url) if url else None,
            }
        )

    if len(ranking_rows) != len(items):
        raise RuntimeError("순위 데이터 생성 중 개수 불일치가 발생했습니다.")

    execute_with_retry(
        supabase.table("rankings")
        .insert(ranking_rows)
    )

    print(f"rankings 저장 성공: {len(ranking_rows)}건")

    # rankings 저장이 실제로 끝난 직후의 시각을 collection_runs.run_at에 다시
    # 기록합니다. 위에서 run_at에 넣은 collected_at은 API 조회 직후(=DB 저장
    # 전) 시각이라 "실제 저장 완료 시각"과는 다릅니다. collected_at(각 rankings
    # 행의 회차 식별자로 계속 쓰이는 값)은 건드리지 않고, 화면 표시용으로만
    # 쓰이는 run_at만 갱신합니다.
    saved_at = datetime.now(timezone.utc).isoformat()
    execute_with_retry(
        supabase.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id)
    )
    print(f"collection_runs.run_at을 실제 저장 완료 시각으로 갱신: {saved_at}")
    print()
    print("=" * 70)
    print("예스24 TOP20 저장 결과")
    print("=" * 70)

    for row in ranking_rows[:20]:
        change = row["rank_change"]
        change_text = "-" if change is None else str(change)
        print(
            f'{row["rank"]:>3}위 | {row["title"]} | '
            f'{row["author"] or "-"} | {row["publisher"] or "-"} | '
            f'ISBN13 {row["isbn13"] or "-"} | 등락 {change_text}'
        )

    print()
    print("테스트 완료.")
    print(f"Supabase run_id: {run_id}")
    print("이제 Supabase의 rankings 테이블에서 100건이 들어갔는지 확인하면 됩니다.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"\n예스24 HTTP 오류: {e}")
        if e.response is not None:
            print("응답:", e.response.text[:1000])
    except Exception as e:
        print(f"\n실행 실패: {e}")
        print("API Key / Supabase URL / Secret Key / 테이블 권한을 확인해주세요.")

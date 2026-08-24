import os
from datetime import datetime, timezone

import requests
from supabase import create_client


YES24_URL = "https://apis.yes24.com/v1/category/bestseller"
CATEGORY_ID = "001"
PAGE_SIZE = 100


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


def main():
    yes24_key = require_env("YES24_API_KEY")
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_KEY")

    # 키 자체는 절대 출력하지 않습니다.
    print("Supabase 클라이언트 생성 중...")
    supabase = create_client(supabase_url, supabase_key)

    items = fetch_yes24()
    collected_at = datetime.now(timezone.utc).isoformat()

    # 1. 이번 수집 실행(run) 기록
    run_result = (
        supabase.table("collection_runs")
        .insert(
            {
                "run_at": collected_at,
                "bookstore": "예스24",
                "status": "success",
                "item_count": len(items),
            }
        )
        .execute()
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
        (
            supabase.table("books")
            .upsert(book_rows, on_conflict="isbn13")
            .execute()
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
            }
        )

    if len(ranking_rows) != len(items):
        raise RuntimeError("순위 데이터 생성 중 개수 불일치가 발생했습니다.")

    (
        supabase.table("rankings")
        .insert(ranking_rows)
        .execute()
    )

    print(f"rankings 저장 성공: {len(ranking_rows)}건")

    # rankings 저장이 실제로 끝난 직후의 시각을 collection_runs.run_at에 다시
    # 기록합니다. 위에서 run_at에 넣은 collected_at은 API 조회 직후(=DB 저장
    # 전) 시각이라 "실제 저장 완료 시각"과는 다릅니다. collected_at(각 rankings
    # 행의 회차 식별자로 계속 쓰이는 값)은 건드리지 않고, 화면 표시용으로만
    # 쓰이는 run_at만 갱신합니다.
    saved_at = datetime.now(timezone.utc).isoformat()
    supabase.table("collection_runs").update({"run_at": saved_at}).eq("id", run_id).execute()
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

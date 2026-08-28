"""분야별(categories.py의 CATEGORIES 14개 분야) TOP20 베스트셀러 수집 -> Supabase 저장.

기존 종합 TOP100 수집 스크립트(test_save_yes24.py)와 동일한 예스24 API
(apis.yes24.com/v1/category/bestseller)와 YES24_API_KEY 환경변수를 그대로
사용하고, categoryId / pageSize 파라미터만 분야별로 바꿔서 호출합니다.
test_save_yes24.py 자체는 전혀 수정하지 않습니다.

주의(categoryId 값에 대해): 이 값은 예스24 공식 API 문서로 직접 확인한 것이
아닙니다. 기존 스크립트가 종합을 categoryId="001"로 쓰고 있고, 예스24
웹사이트(yes24.com)의 categoryNumber=001도 "국내도서 종합"을 가리키는 것이
확인되어, 이 API가 웹사이트와 동일한 categoryNumber 체계를 쓴다고 보고
분야별 값을 대응시켰습니다(categories.py 참고). 최초 실행 시 콘솔에 출력되는
수집 결과(도서 제목)가 해당 분야와 다르게 나온다면 categories.py의
yes24_category_id 값을 실제 API 응답에 맞게 조정해야 합니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY, YES24_API_KEY (기존과 동일)
"""

import os
import sys
from datetime import datetime, timezone

import requests

try:
    from supabase import create_client
except ImportError:
    print("오류: supabase 라이브러리가 설치되어 있지 않습니다. (pip install supabase)")
    sys.exit(1)

from categories import CATEGORIES, TOP_N
from supabase_retry import execute_with_retry

YES24_URL = "https://apis.yes24.com/v1/category/bestseller"
BOOKSTORE = "예스24"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} 환경변수가 없습니다.")
    return value


def fetch_yes24_category(api_key: str, category_id: str, page_size: int):
    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }
    params = {
        "categoryId": category_id,
        "page": 1,
        "pageSize": page_size,
    }

    response = requests.get(YES24_URL, headers=headers, params=params, timeout=30)
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
    return items


def main():
    yes24_key = require_env("YES24_API_KEY")
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_KEY")

    print("Supabase 클라이언트 생성 중...")
    client = create_client(supabase_url, supabase_key)
    collected_at = datetime.now(timezone.utc).isoformat()

    all_rows = []
    category_errors = {}

    for cat in CATEGORIES:
        category = cat["category"]
        category_id = cat["yes24_category_id"]
        print(f"\n=== 예스24 · {category} TOP{TOP_N} 수집 시작 (categoryId={category_id}) ===")
        try:
            items = fetch_yes24_category(yes24_key, category_id, TOP_N)

            for item in items:
                rank = item.get("sortOrder")
                title = str(item.get("title") or "").strip()
                author = str(item.get("author") or "").strip() or None
                publisher = str(item.get("publisher") or "").strip() or None
                isbn13 = str(item.get("isbn13") or "").strip() or None
                url = str(item.get("link") or "").strip() or None

                raw_change = item.get("upDown")
                try:
                    rank_change = int(raw_change) if raw_change is not None else None
                except (TypeError, ValueError):
                    rank_change = None

                all_rows.append(
                    {
                        "collected_at": collected_at,
                        "bookstore": BOOKSTORE,
                        "category": category,
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
            print(f"   -> {category} {len(items)}권 수집 성공")
        except Exception as e:
            category_errors[category] = str(e)
            print(f"   -> {category} 수집 실패: {e}")

    status = "success" if all_rows else "failed"
    error_message = "; ".join(f"{c}: {m}" for c, m in category_errors.items()) or None

    run_result = execute_with_retry(
        client.table("collection_runs")
        .insert(
            {
                "run_at": collected_at,
                "bookstore": BOOKSTORE,
                "status": status,
                "error_message": error_message,
                "item_count": len(all_rows),
            }
        )
    )
    if not run_result.data:
        raise RuntimeError("collection_runs 저장에 실패했습니다.")

    run_id = run_result.data[0]["id"]
    print(f"\ncollection_runs 저장 성공: run_id={run_id}, status={status}, 총 {len(all_rows)}권")

    if not all_rows:
        print("저장할 도서 데이터가 없어 books/rankings 저장은 건너뜁니다.")
        sys.exit(1)

    book_rows = []
    seen_isbn = set()
    for row in all_rows:
        isbn13 = row.get("isbn13")
        if not isbn13 or isbn13 in seen_isbn:
            continue
        seen_isbn.add(isbn13)
        book_rows.append(
            {
                "isbn13": isbn13,
                "title": row["title"],
                "author": row["author"],
                "publisher": row["publisher"],
                "updated_at": collected_at,
            }
        )

    if book_rows:
        supabase_result = execute_with_retry(
            client.table("books").upsert(book_rows, on_conflict="isbn13")
        )
        print(f"books 저장/갱신 성공: {len(supabase_result.data)}권")
    else:
        print("books 저장/갱신 성공: 0권")

    ranking_rows = [{**row, "run_id": run_id} for row in all_rows]
    execute_with_retry(client.table("rankings").insert(ranking_rows))
    print(f"rankings 저장 성공: {len(ranking_rows)}건")

    if category_errors:
        print("\n일부 분야 수집 실패:")
        for c, m in category_errors.items():
            print(f"  - {c}: {m}")

    print()
    print("=" * 70)
    print("분야별(예스24) 수집 결과 요약")
    print("=" * 70)
    for cat in CATEGORIES:
        cat_rows = [r for r in all_rows if r["category"] == cat["category"]]
        print(f"[{cat['category']}] {len(cat_rows)}권")
        for r in sorted(cat_rows, key=lambda x: x["rank"]):
            print(
                f'   {r["rank"]:>3}위 | {r["title"]} | {r["author"] or "-"} | '
                f'{r["publisher"] or "-"} | ISBN13 {r["isbn13"] or "-"}'
            )


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"\n예스24 HTTP 오류: {e}")
        if e.response is not None:
            print("응답:", e.response.text[:1000])
        sys.exit(1)
    except Exception as e:
        print(f"\n실행 실패: {e}")
        print("API Key / Supabase URL / Secret Key / 테이블 권한을 확인해주세요.")
        sys.exit(1)

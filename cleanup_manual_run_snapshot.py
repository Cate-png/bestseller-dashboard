"""[일회성 정리 스크립트 - 완료 후 삭제 예정]

2026-08-25 11:44경(KST) 수동 workflow_dispatch 실행(collect.yml)으로 잘못
생성된 종합 TOP100 스냅샷 3건(run_id 88/90/91)만 정확히 골라서 삭제합니다.

안전장치:
- 대상은 run_id IN (88, 90, 91)로 하드코딩되어 있고, 그 외 run_id는 절대
  건드리지 않습니다.
- collection_runs 테이블은 전혀 건드리지 않습니다(rankings만 삭제).
- 삭제 전에 반드시 bookstore별/category별 건수를 세어, 기대값(교보문고 100,
  알라딘 100, 예스24 100, category 전부 "종합", 총 300건)과 정확히 일치할
  때만 삭제를 진행합니다. 하나라도 다르면 그 자리에서 중단하고 삭제하지
  않습니다.
- 삭제 후 같은 run_id로 다시 조회해 0건인지 검증합니다.
- 삭제 후 각 서점의 남은 종합(category="종합") 최신 스냅샷의 run_id/
  collected_at을 출력해, 정상적인 이전 수집 데이터가 최신으로 잡히는지
  확인할 수 있게 합니다.
"""
import os
import sys
from collections import Counter

try:
    from supabase import create_client
except ImportError:
    print("오류: supabase 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

TARGET_RUN_IDS = [88, 90, 91]
EXPECTED_TOTAL = 300
EXPECTED_PER_STORE = {"교보문고": 100, "알라딘": 100, "예스24": 100}


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("=" * 70)
    print(f"1단계: run_id IN {TARGET_RUN_IDS} 확인용 SELECT (읽기 전용)")
    print("=" * 70)

    result = (
        client.table("rankings")
        .select("id, run_id, bookstore, category, collected_at")
        .in_("run_id", TARGET_RUN_IDS)
        .execute()
    )
    rows = result.data
    total = len(rows)
    by_store = Counter(r["bookstore"] for r in rows)
    by_run = Counter(r["run_id"] for r in rows)
    categories = Counter(r["category"] for r in rows)

    print(f"총 건수: {total}건")
    print(f"run_id별 건수: {dict(by_run)}")
    print(f"bookstore별 건수: {dict(by_store)}")
    print(f"category별 건수: {dict(categories)}")

    ok = (
        total == EXPECTED_TOTAL
        and by_store == Counter(EXPECTED_PER_STORE)
        and set(categories.keys()) == {"종합"}
    )

    if not ok:
        print("\n중단: 예상값(교보문고 100 / 알라딘 100 / 예스24 100, 전부 종합, "
              "총 300건)과 실제 조회 결과가 다릅니다. 삭제를 실행하지 않습니다.")
        sys.exit(1)

    print("\n확인 완료: 예상값과 정확히 일치합니다. 삭제를 진행합니다.")

    print("\n" + "=" * 70)
    print(f"2단계: DELETE FROM rankings WHERE run_id IN {TARGET_RUN_IDS}")
    print("=" * 70)
    delete_result = (
        client.table("rankings")
        .delete()
        .in_("run_id", TARGET_RUN_IDS)
        .execute()
    )
    print(f"삭제된 행 수(응답 기준): {len(delete_result.data)}건")

    print("\n" + "=" * 70)
    print("3단계: 삭제 검증 (같은 run_id로 재조회, 0건이어야 정상)")
    print("=" * 70)
    verify = (
        client.table("rankings")
        .select("id", count="exact")
        .in_("run_id", TARGET_RUN_IDS)
        .execute()
    )
    remaining = verify.count
    print(f"삭제 후 남은 건수: {remaining}건")
    if remaining != 0:
        print("경고: 삭제 후에도 데이터가 남아 있습니다. 확인이 필요합니다.")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("4단계: 각 서점의 남은 종합(category=\"종합\") 최신 스냅샷 확인")
    print("=" * 70)
    for bookstore in ["교보문고", "알라딘", "예스24"]:
        latest = (
            client.table("rankings")
            .select("run_id, collected_at")
            .eq("bookstore", bookstore)
            .eq("category", "종합")
            .order("collected_at", desc=True)
            .limit(1)
            .execute()
        )
        if latest.data:
            row = latest.data[0]
            print(f"  {bookstore}: run_id={row['run_id']}, collected_at={row['collected_at']}")
        else:
            print(f"  {bookstore}: 종합 스냅샷 없음")

    print("\n정리 완료.")


if __name__ == "__main__":
    main()

"""[읽기 전용 진단 - 완료 후 삭제 예정]

방금 run_id 88/90/91(오늘 11:44경 수동 실행분)을 삭제한 뒤, 대시보드가
쓰는 각 서점 최신 종합(category="종합") 스냅샷의 store_category 상태를
확인합니다. Supabase에 아무것도 쓰지 않습니다(SELECT만).
"""
import os
import sys

try:
    from supabase import create_client
except ImportError:
    print("오류: supabase 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)


def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("=" * 70)
    print("1) 각 서점의 현재 최신 종합(category=\"종합\") 스냅샷 + store_category 상태")
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
        if not latest.data:
            print(f"  {bookstore}: 종합 스냅샷 없음")
            continue
        run_id = latest.data[0]["run_id"]
        collected_at = latest.data[0]["collected_at"]

        rows = (
            client.table("rankings")
            .select("store_category")
            .eq("bookstore", bookstore)
            .eq("category", "종합")
            .eq("run_id", run_id)
            .execute()
        )
        total = len(rows.data)
        null_count = sum(1 for r in rows.data if not r.get("store_category"))
        filled_count = total - null_count
        print(
            f"  {bookstore}: run_id={run_id}, collected_at={collected_at}, "
            f"총 {total}건 중 store_category NULL/빈값 {null_count}건, "
            f"값 있음 {filled_count}건"
        )

    print()
    print("=" * 70)
    print("2) store_category가 실제로 채워진 가장 최근 종합 run (전체 서점 통틀어)")
    print("=" * 70)
    recent_filled = (
        client.table("rankings")
        .select("run_id, bookstore, collected_at, store_category")
        .eq("category", "종합")
        .not_.is_("store_category", "null")
        .order("collected_at", desc=True)
        .limit(5)
        .execute()
    )
    if not recent_filled.data:
        print("  store_category가 채워진 종합 데이터가 현재 하나도 없습니다.")
    else:
        seen_runs = set()
        for row in recent_filled.data:
            key = (row["bookstore"], row["run_id"])
            if key in seen_runs:
                continue
            seen_runs.add(key)
            print(
                f"  bookstore={row['bookstore']}, run_id={row['run_id']}, "
                f"collected_at={row['collected_at']}, "
                f"store_category 예시={row['store_category']!r}"
            )
        target_run_ids = {88, 90, 91}
        found_run_ids = {r["run_id"] for r in recent_filled.data}
        print(
            f"\n  이 결과들이 삭제한 run_id(88/90/91)와 겹치는가: "
            f"{bool(found_run_ids & target_run_ids)} (겹치는 run_id: {found_run_ids & target_run_ids or '없음'})"
        )

    print("\n진단 완료.")


if __name__ == "__main__":
    main()

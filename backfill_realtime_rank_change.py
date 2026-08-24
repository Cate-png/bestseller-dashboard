"""realtime_rankings의 과거 rank_change 값 중, ISBN13 충돌 버그(교보문고 등
같은 ISBN13을 공유하는 종이책/전자책이 한 회차에 함께 있을 때 서로의 순위를
덮어써 등락이 잘못 계산되던 문제 - test_save_kyobo_realtime.py /
test_save_yes24_realtime.py / test_save_aladin_realtime.py의
get_previous_realtime_ranks() 수정 건)로 잘못 저장된 값을 소급 수정합니다.

방식:
- 서점별로 realtime_rankings 전체 행을 collected_at 오름차순으로 가져와
  회차(=같은 collected_at) 단위로 묶습니다.
- 각 회차 i(i>0)에 대해, 바로 직전 회차(i-1)의 (isbn13, url) -> rank 매핑을
  만들고(수정된 로직과 동일), 회차 i의 각 행에 대해 rank_change를 다시
  계산합니다.
- 재계산 값이 저장된 값과 다른 행만 UPDATE합니다(그 외 행은 이미 정확하므로
  건드리지 않음 - 이미 배포된 실시간 대시보드 화면 로직/스키마와 무관하게
  rank_change 컬럼 값만 고칩니다).
- 가장 오래된 회차(각 서점의 첫 회차)는 비교할 직전 회차가 없으므로 항상
  rank_change=None이 정답이며, 이미 그렇게 저장돼 있을 것이므로 보통 변경이
  없습니다.

기본은 --apply 없이 실행하면 무엇이 바뀔지만 보여주는 드라이런입니다.
실제로 DB를 고치려면 --apply를 반드시 붙여야 합니다.

수집 로직, 스키마, cron, 프론트엔드는 전혀 건드리지 않습니다 - 이미 저장된
realtime_rankings.rank_change 컬럼 값만 고칩니다.

필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
사용법:
  python backfill_realtime_rank_change.py            # 드라이런(미리보기만)
  python backfill_realtime_rank_change.py --apply     # 실제로 DB에 반영
"""

import os
import sys

from supabase import create_client

BOOKSTORES = ["교보문고", "예스24", "알라딘"]
PAGE_SIZE = 1000


def fetch_all_rows(client, bookstore):
    """이 서점의 realtime_rankings 전체 행을 collected_at 오름차순, 페이지
    단위(PAGE_SIZE)로 끝까지 가져옵니다."""
    rows = []
    offset = 0
    while True:
        res = (
            client.table("realtime_rankings")
            .select("id, collected_at, isbn13, url, rank, rank_change")
            .eq("bookstore", bookstore)
            .order("collected_at", desc=False)
            .order("id", desc=False)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def group_by_round(rows):
    """collected_at 값이 같은 행들을 한 회차로 묶어, 회차를 시간순 리스트로
    돌려줍니다(각 회차는 dict 행 리스트)."""
    rounds = {}
    order = []
    for row in rows:
        key = row["collected_at"]
        if key not in rounds:
            rounds[key] = []
            order.append(key)
        rounds[key].append(row)
    return [rounds[k] for k in order]


def build_prev_ranks(prev_round_rows):
    return {
        (row["isbn13"], row["url"]): row["rank"]
        for row in prev_round_rows
        if row["isbn13"]
    }


def recompute_rank_change(prev_ranks, row):
    isbn13 = row["isbn13"]
    if not isbn13:
        return None
    key = (isbn13, row["url"])
    if key not in prev_ranks:
        return None
    return prev_ranks[key] - row["rank"]


def main():
    apply = "--apply" in sys.argv[1:]

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("오류: SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 필요합니다.")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print(f"모드: {'실제 반영(--apply)' if apply else '드라이런(미리보기만, DB 변경 없음)'}\n")

    total_mismatches = 0
    total_updated = 0

    for bookstore in BOOKSTORES:
        print(f"=== {bookstore} ===")
        rows = fetch_all_rows(client, bookstore)
        print(f"전체 행 수: {len(rows)}건")

        rounds = group_by_round(rows)
        print(f"회차 수: {len(rounds)}개")

        mismatches = []
        for i in range(1, len(rounds)):
            prev_ranks = build_prev_ranks(rounds[i - 1])
            for row in rounds[i]:
                expected = recompute_rank_change(prev_ranks, row)
                stored = row["rank_change"]
                if expected != stored:
                    mismatches.append(
                        {
                            "id": row["id"],
                            "collected_at": row["collected_at"],
                            "isbn13": row["isbn13"],
                            "url": row["url"],
                            "rank": row["rank"],
                            "stored": stored,
                            "expected": expected,
                        }
                    )

        print(f"불일치 발견: {len(mismatches)}건")
        for m in mismatches[:20]:
            print(
                f"  - id={m['id']} collected_at={m['collected_at']} rank={m['rank']} "
                f"isbn13={m['isbn13']} : stored={m['stored']} -> expected={m['expected']}"
            )
        if len(mismatches) > 20:
            print(f"  ... 외 {len(mismatches) - 20}건 더")

        total_mismatches += len(mismatches)

        if apply and mismatches:
            updated = 0
            for m in mismatches:
                client.table("realtime_rankings").update(
                    {"rank_change": m["expected"]}
                ).eq("id", m["id"]).execute()
                updated += 1
            print(f"실제 반영 완료: {updated}건 UPDATE")
            total_updated += updated

        print()

    print("=" * 60)
    print(f"전체 불일치: {total_mismatches}건")
    if apply:
        print(f"전체 반영: {total_updated}건")
    else:
        print("드라이런이었습니다 - 실제로 반영하려면 --apply를 붙여 다시 실행하세요.")


if __name__ == "__main__":
    main()

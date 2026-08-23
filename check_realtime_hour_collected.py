"""collect-realtime.yml이 "이번 KST 시간대"에 이 서점 데이터를 이미 정상
수집했는지 확인합니다. GitHub Actions schedule을 5분 간격(매시 01, 06, 11,
...56분)으로 여러 번 실행하되, 같은 시간대(예: 13시)에 이미 성공한 수집이
있으면 already_collected=true를 GITHUB_OUTPUT에 써서 크롤링 스텝을
건너뛰게 합니다(중복 수집 방지). 반대로 13:01 실행이 GitHub Actions
schedule 지연/누락으로 통째로 스킵됐다면, 13:06(또는 그 다음 회차) 실행에서
이 스크립트가 "13시 데이터 없음"을 확인하고 크롤링을 그대로 진행합니다.

시간대 판단 기준은 components/Dashboard.jsx의 endOfHourISO()와 동일하게
"KST 기준 그 시(0~23)의 00:00:00 ~ 59:59.999"를 한 회차로 봅니다. KST는
UTC+9 정수 시간 오프셋(서머타임 없음)이라 "KST 시(hour) 경계"와 "UTC
시(hour) 경계"는 항상 같은 순간에 일어납니다(예: KST 13:00:00 == UTC
04:00:00, KST 13:59:59.999 == UTC 04:59:59.999). 그래서
datetime.now(timezone.utc)를 UTC 기준으로 정시 단위로 내림(floor)한
구간이 "지금 KST 회차" 구간과 정확히 일치하며, 타임존 변환 없이 UTC
시각만으로 정확한 KST 시간대 경계를 구할 수 있습니다.

"이미 수집됐는지"는 realtime_rankings에서 해당 서점 + 이번 시간대 구간에
행이 1건이라도 있는지로 판단합니다. test_save_kyobo_realtime.py /
test_save_yes24_realtime.py / test_save_aladin_realtime.py 세 스크립트
모두 수집이 성공(도서를 1권 이상 확보)했을 때만 realtime_rankings에
insert하고, 실패하면 insert 없이 종료하므로(sys.exit(1)) "1건 이상 존재"는
곧 "그 시간대에 정상 수집 완료"와 동일합니다. app/page.js,
app/api/history/route.js가 "가장 최근 스냅샷 존재 여부"로 성공을 판단하는
기존 방식과 동일한 전제입니다.

이 스크립트 자체가 실패해도(Supabase 조회 오류 등) 기본값은 안전하게
"수집 필요(already_collected=false)"로 둡니다. 판단 오류로 실제 수집을
건너뛰어 그 시간대 데이터가 통째로 비는 것보다, 같은 시간대에 중복 수집이
한 번 더 일어나는 편이 훨씬 안전하기 때문입니다.

기존 3개 실시간 수집 스크립트의 크롤링 로직, realtime_rankings /
realtime_collection_runs 테이블 구조는 전혀 건드리지 않습니다.

사용법: python check_realtime_hour_collected.py <서점명>
필요 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY
출력: GITHUB_OUTPUT에 already_collected=true|false 기록
"""

import os
import sys
from datetime import datetime, timedelta, timezone


def write_output(already_collected: bool) -> None:
    value = "true" if already_collected else "false"
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"already_collected={value}\n")
    print(f"already_collected={value}")


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("사용법: python check_realtime_hour_collected.py <서점명>")
        sys.exit(1)
    bookstore = sys.argv[1]

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("경고: SUPABASE_URL / SUPABASE_SERVICE_KEY가 없어 기존 수집 여부를 확인할 수 없습니다. 안전하게 수집을 진행합니다.")
        write_output(False)
        return

    now_utc = datetime.now(timezone.utc)
    hour_start = now_utc.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)
    kst_hour = (hour_start.hour + 9) % 24
    print(f"{bookstore}: 이번 회차(KST {kst_hour:02d}시) 조회 구간(UTC) = {hour_start.isoformat()} ~ {hour_end.isoformat()}")

    try:
        from supabase import create_client

        client = create_client(supabase_url, supabase_key)
        existing = (
            client.table("realtime_rankings")
            .select("collected_at")
            .eq("bookstore", bookstore)
            .gte("collected_at", hour_start.isoformat())
            .lt("collected_at", hour_end.isoformat())
            .limit(1)
            .execute()
        )
        already_collected = bool(existing.data)
    except Exception as e:
        print(f"경고: {bookstore}의 기존 수집 여부 확인 중 오류가 발생했습니다({e}). 안전하게 수집을 진행합니다.")
        write_output(False)
        return

    if already_collected:
        print(f"{bookstore}: KST {kst_hour:02d}시 회차 데이터가 이미 있습니다. 이번 실행에서는 수집을 건너뜁니다.")
    else:
        print(f"{bookstore}: KST {kst_hour:02d}시 회차 데이터가 아직 없습니다. 수집을 진행합니다.")
    write_output(already_collected)


if __name__ == "__main__":
    main()

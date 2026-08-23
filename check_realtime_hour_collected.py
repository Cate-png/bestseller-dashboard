"""collect-realtime.yml이 "이번 30분 슬롯"에 이 서점 데이터를 이미 정상
수집했는지 확인합니다.

2026-08-24: 기존에는 "이번 KST 시간대(정시~59분)" 단위로 판단했지만,
실시간 수집 주기를 1시간 -> 30분(매시 00분 + 30분)으로 전환하면서 판단
단위도 시간(hour)에서 30분 슬롯으로 좁혔습니다. 외부 cron 서비스가
GitHub REST API(workflow_dispatch)를 매시 00분/30분에 각각 호출하는
구조 자체는 그대로이고(cron-job.org 쪽 스케줄 설정을 30분 간격으로
바꾸는 작업은 이 저장소 밖에서 별도로 해야 합니다 - 이 스크립트만
고쳐서는 실제 호출 빈도가 자동으로 바뀌지 않습니다), 같은 슬롯(예:
13:00~13:29)에 이미 성공한 수집이 있으면 already_collected=true를
GITHUB_OUTPUT에 써서 크롤링 스텝을 건너뛰게 합니다(중복 수집 방지).
반대로 13:00 실행이 지연/누락으로 통째로 스킵됐다면, 13:30(다음 슬롯)
실행은 "13:00~13:29 슬롯"이 아니라 "13:30~13:59 슬롯"을 확인하므로
평소와 같이 정상적으로 수집을 진행합니다 - 즉 이번 변경은 "놓친 이전
슬롯을 대신 채워주는" 기능이 아니라(이전과 동일하게 그런 보충 기능은
없음), 단지 판단 단위 자체를 30분으로 좁힌 것입니다.

슬롯 판단 기준은 "KST 기준 00분 또는 30분부터 시작하는 30분 구간"입니다.
KST는 UTC+9 정수 시간 오프셋(서머타임 없음)이고 9시간(540분)은 30분의
배수이므로, "KST 30분 슬롯 경계"와 "UTC 30분 슬롯 경계"는 항상 같은
순간에 일어납니다(예: KST 13:30:00 == UTC 04:30:00, KST 13:59:59.999
== UTC 04:59:59.999). 그래서 datetime.now(timezone.utc)를 UTC 기준으로
30분 단위로 내림(floor)한 구간이 "지금 KST 슬롯" 구간과 정확히
일치하며, 타임존 변환 없이 UTC 시각만으로 정확한 KST 슬롯 경계를 구할
수 있습니다.

"이미 수집됐는지"는 realtime_rankings에서 해당 서점 + 이번 슬롯 구간에
행이 1건이라도 있는지로 판단합니다. test_save_kyobo_realtime.py /
test_save_yes24_realtime.py / test_save_aladin_realtime.py 세 스크립트
모두 수집이 성공(도서를 1권 이상 확보)했을 때만 realtime_rankings에
insert하고, 실패하면 insert 없이 종료하므로(sys.exit(1)) "1건 이상 존재"는
곧 "그 슬롯에 정상 수집 완료"와 동일합니다. 세 스크립트는 언제나 새
행을 insert만 할 뿐 기존 행을 update/삭제하지 않으므로(불변 스냅샷),
이 판단 로직을 30분 단위로 좁혀도 과거에 저장된 데이터에는 전혀 영향이
없습니다.

이 스크립트 자체가 실패해도(Supabase 조회 오류 등) 기본값은 안전하게
"수집 필요(already_collected=false)"로 둡니다. 판단 오류로 실제 수집을
건너뛰어 그 슬롯 데이터가 통째로 비는 것보다, 같은 슬롯에 중복 수집이
한 번 더 일어나는 편이 훨씬 안전하기 때문입니다.

기존 3개 실시간 수집 스크립트의 크롤링 로직, realtime_rankings /
realtime_collection_runs 테이블 구조, collected_at(실제 수집 시각을
datetime.now(timezone.utc)로 기록하는 방식)은 전혀 건드리지 않습니다.
분야별 베스트셀러 수집(collect.yml, categories.py 등)과도 무관합니다.

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
    slot_minute = 0 if now_utc.minute < 30 else 30  # 30분 슬롯 시작점(00분 또는 30분)으로 내림
    slot_start = now_utc.replace(minute=slot_minute, second=0, microsecond=0)
    slot_end = slot_start + timedelta(minutes=30)
    kst_slot_start = slot_start + timedelta(hours=9)
    slot_label = f"{kst_slot_start.hour:02d}:{kst_slot_start.minute:02d}"
    print(f"{bookstore}: 이번 회차(KST {slot_label} 슬롯) 조회 구간(UTC) = {slot_start.isoformat()} ~ {slot_end.isoformat()}")

    try:
        from supabase import create_client

        client = create_client(supabase_url, supabase_key)
        existing = (
            client.table("realtime_rankings")
            .select("collected_at")
            .eq("bookstore", bookstore)
            .gte("collected_at", slot_start.isoformat())
            .lt("collected_at", slot_end.isoformat())
            .limit(1)
            .execute()
        )
        already_collected = bool(existing.data)
    except Exception as e:
        print(f"경고: {bookstore}의 기존 수집 여부 확인 중 오류가 발생했습니다({e}). 안전하게 수집을 진행합니다.")
        write_output(False)
        return

    if already_collected:
        print(f"{bookstore}: KST {slot_label} 슬롯 데이터가 이미 있습니다. 이번 실행에서는 수집을 건너뜁니다.")
    else:
        print(f"{bookstore}: KST {slot_label} 슬롯 데이터가 아직 없습니다. 수집을 진행합니다.")
    write_output(already_collected)


if __name__ == "__main__":
    main()

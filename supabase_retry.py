"""수집 스크립트(test_save_*.py)의 Supabase 호출에 공통으로 쓰는 재시도 헬퍼.

Supabase(PostgREST)가 간헐적으로 "JWT issued at future"(에러코드 PGRST303)를
돌려줄 때가 있습니다. 이건 우리 코드나 서비스 키의 iat/exp 문제가 아니라,
Supabase 인프라 내부에서 JWT를 발급하는 쪽과 PostgREST가 검증하는 쪽의 시계가
순간적으로(수 초~수십 초) 어긋날 때 PostgREST가 요청을 거부하는 것으로,
Supabase 커뮤니티에서도 알려진 서버 측 clock-skew 현상입니다
(https://github.com/orgs/supabase/discussions/48123).

lib/supabaseServer.js(Next.js 프론트엔드의 읽기 쪽)에는 이미 동일한 오류에 대한
재시도 로직이 있는데, 수집 스크립트(쓰기 쪽)에는 없어서 이 오류가 한 번 나면
그 회차 전체가 통째로 실패하고(예: 2026-08-28 알라딘 일간 수집), 다음 정상
회차까지 대시보드가 오래된 스냅샷을 계속 보여주게 됩니다. 프론트와 원인이
같으므로 같은 완화책(짧은 지연 후 최대 3회 재시도)을 그대로 적용합니다. 이
오류가 아닌 다른 실패(진짜 인증 실패, 스키마 오류, 네트워크 오류 등)는
재시도 없이 그대로 올려서 각 스크립트의 기존 예외 처리 흐름을 그대로 탑니다.
"""

import time

from postgrest.exceptions import APIError

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.5


def _is_jwt_clock_skew_error(e: APIError) -> bool:
    if getattr(e, "code", None) == "PGRST303":
        return True
    message = str(getattr(e, "message", "") or "")
    return "issued at future" in message.lower()


def execute_with_retry(query):
    """query.execute()를 실행하되, PGRST303("JWT issued at future")일 때만
    짧은 지연 후 최대 MAX_ATTEMPTS번까지 재시도합니다. 그 외 오류는 즉시
    그대로 올립니다."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return query.execute()
        except APIError as e:
            if not _is_jwt_clock_skew_error(e) or attempt == MAX_ATTEMPTS:
                raise
            time.sleep(BASE_DELAY_SECONDS * attempt)

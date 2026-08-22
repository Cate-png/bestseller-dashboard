import { createClient } from "@supabase/supabase-js";

// 이 파일은 서버 컴포넌트(app/page.js)에서만 사용됩니다.
// SUPABASE_SERVICE_KEY는 절대 브라우저로 전송되지 않습니다 (Server Component에서만 실행됨).

// Supabase(PostgREST)가 간헐적으로 "JWT issued at future"(에러코드 PGRST303)를
// 돌려줄 때가 있습니다. 이건 우리 코드나 이 서비스 키의 iat/exp 문제가 아니라,
// Supabase 인프라 내부에서 JWT를 발급하는 쪽과 PostgREST가 검증하는 쪽의 시계가
// 순간적으로(수 초~수십 초) 어긋날 때 PostgREST가 요청을 거부하는 것으로,
// Supabase 커뮤니티에서도 알려진 서버 측 clock-skew 현상입니다
// (https://github.com/orgs/supabase/discussions/48123). 실제로 브라우저를
// 새로고침하면 곧바로 정상화되는데, 이는 재요청이 다른(정상 동기화된) 백엔드로
// 라우팅되며 우회되기 때문으로 보입니다. 날짜/시간 조회 로직이나 collected_at
// 처리와는 무관하므로 그쪽은 건드리지 않고, 이 특정 오류에 한해서만 아주 짧게
// 재시도합니다 - supabase-js가 공식 지원하는 global.fetch 훅을 이용해 모든
// Supabase 호출(app/page.js, app/api/history, app/api/book-history 전부)에
// 호출부 수정 없이 한 곳에서 일괄 적용됩니다. 이 오류가 아닌 다른 실패(진짜
// 인증 실패, 네트워크 오류 등)는 재시도 없이 그대로 반환해 기존 에러 처리
// 흐름(각 라우트의 try/catch)을 그대로 탑니다.
const JWT_CLOCK_SKEW_MAX_ATTEMPTS = 3;

async function isJwtIssuedAtFutureError(response) {
  if (response.status !== 401 && response.status !== 403) return false;
  try {
    const body = await response.clone().json();
    if (body && body.code === "PGRST303") return true;
    if (typeof body?.message === "string" && /issued at future/i.test(body.message)) {
      return true;
    }
  } catch (e) {
    // JSON이 아닌 응답이면 이 오류가 아님 - 그냥 원래 응답을 그대로 씁니다.
  }
  return false;
}

async function fetchWithJwtClockSkewRetry(input, init) {
  let response = await fetch(input, init);
  for (
    let attempt = 1;
    attempt < JWT_CLOCK_SKEW_MAX_ATTEMPTS && (await isJwtIssuedAtFutureError(response));
    attempt++
  ) {
    await new Promise((resolve) => setTimeout(resolve, 200 * attempt));
    response = await fetch(input, init);
  }
  return response;
}

export function getSupabaseServerClient() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;

  if (!url || !key) {
    throw new Error(
      "SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 설정되어 있지 않습니다. " +
        ".env.local 파일을 확인해주세요."
    );
  }

  return createClient(url, key, {
    global: { fetch: fetchWithJwtClockSkewRetry },
  });
}

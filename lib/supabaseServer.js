import { createClient } from "@supabase/supabase-js";

// 이 파일은 서버 컴포넌트(app/page.js)에서만 사용됩니다.
// SUPABASE_SERVICE_KEY는 절대 브라우저로 전송되지 않습니다 (Server Component에서만 실행됨).
export function getSupabaseServerClient() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;

  if (!url || !key) {
    throw new Error(
      "SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 설정되어 있지 않습니다. " +
        ".env.local 파일을 확인해주세요."
    );
  }

  return createClient(url, key);
}

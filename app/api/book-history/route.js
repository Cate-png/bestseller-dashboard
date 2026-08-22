import { NextResponse } from "next/server";
import { getSupabaseServerClient } from "../../../lib/supabaseServer";

// 특정 도서(isbn13)의 서점별 과거 순위 시계열을 반환하는 서버 API.
// Dashboard.jsx의 "📈 순위 변화" 버튼이 이 라우트를 호출합니다. Supabase
// 접속은 항상 이 서버 라우트 안에서만 이뤄지고 브라우저로 키가 노출되지
// 않습니다(app/api/history/route.js와 동일한 원칙).
//
// scope=total    -> rankings 테이블, category="종합"
// scope=category -> rankings 테이블, category=<category 파라미터>
// scope=realtime -> realtime_rankings 테이블 (category 개념 없음)
//
// 저장된 모든 스냅샷 중 이 isbn13이 그 서점 순위권(TOP100/TOP10)에 있었던
// 시점의 (collected_at, rank) 행만 그대로 반환합니다. 순위권 밖으로 밀린
// 시점은 애초에 행이 없으므로(결측) 이 응답에도 나타나지 않습니다 - 차트
// 쪽에서 점을 그대로 이어 표시합니다.

const BOOKSTORES = ["교보문고", "예스24", "알라딘"];

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const isbn13 = searchParams.get("isbn13");
  const scope = searchParams.get("scope");
  const category = searchParams.get("category");

  if (!isbn13 || !scope) {
    return NextResponse.json(
      { error: "isbn13, scope 파라미터가 필요합니다." },
      { status: 400 }
    );
  }
  if (scope === "category" && !category) {
    return NextResponse.json(
      { error: "scope=category일 때는 category 파라미터가 필요합니다." },
      { status: 400 }
    );
  }

  let client;
  try {
    client = getSupabaseServerClient();
  } catch (e) {
    return NextResponse.json({ error: String(e.message || e) }, { status: 500 });
  }

  const table = scope === "realtime" ? "realtime_rankings" : "rankings";
  const categoryValue =
    scope === "total" ? "종합" : scope === "category" ? category : null;

  const series = {};
  let bookInfo = null;

  try {
    await Promise.all(
      BOOKSTORES.map(async (bookstore) => {
        let q = client
          .from(table)
          .select("collected_at, rank, title, author, publisher")
          .eq("bookstore", bookstore)
          .eq("isbn13", isbn13)
          .order("collected_at", { ascending: true });
        if (categoryValue !== null) {
          q = q.eq("category", categoryValue);
        }

        const { data, error } = await q;
        if (error) throw error;

        series[bookstore] = (data || []).map((row) => ({
          collectedAt: row.collected_at,
          rank: row.rank,
        }));

        if (!bookInfo && data && data.length > 0) {
          const last = data[data.length - 1];
          bookInfo = {
            title: last.title,
            author: last.author,
            publisher: last.publisher,
          };
        }
      })
    );
  } catch (e) {
    return NextResponse.json({ error: String(e.message || e) }, { status: 500 });
  }

  return NextResponse.json({ bookInfo, series });
}

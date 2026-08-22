import { NextResponse } from "next/server";
import { getSupabaseServerClient } from "../../../lib/supabaseServer";

// 과거 기록 조회 API. 클라이언트(Dashboard.jsx)가 날짜/시간을 선택하면
// 이 라우트를 호출해, 그 시점 "이전(또는 그 시점)의 가장 최근 스냅샷"을
// 서점별로 찾아 반환합니다. Supabase 접속(SUPABASE_SERVICE_KEY)은 항상
// 이 서버 라우트 안에서만 이뤄지고 브라우저로 전달되지 않습니다
// (lib/supabaseServer.js와 동일한 원칙).
//
// scope=total    -> rankings 테이블, category="종합"
// scope=category -> rankings 테이블, category=<category 파라미터>
// scope=realtime -> realtime_rankings 테이블 (category 개념 없음)
//
// 기존 app/page.js의 "가장 최근" 조회 로직과 동일한 2단계 조회(먼저
// collected_at을 찾고, 그 값으로 전체 행을 가져오는) 방식을 그대로 쓰되,
// "가장 최근" 대신 "at 파라미터 이전(<=) 중 가장 최근"으로만 바꿨습니다.

const BOOKSTORES = ["교보문고", "예스24", "알라딘"];

async function getSnapshotAtOrBefore(client, table, bookstore, category, at) {
  let latestQuery = client
    .from(table)
    .select("collected_at")
    .eq("bookstore", bookstore)
    .lte("collected_at", at)
    .order("collected_at", { ascending: false })
    .limit(1);
  if (category !== null) {
    latestQuery = latestQuery.eq("category", category);
  }

  const latest = await latestQuery;
  if (latest.error) throw latest.error;
  if (!latest.data || latest.data.length === 0) {
    return { collectedAt: null, rows: [] };
  }

  const collectedAt = latest.data[0].collected_at;

  let rowsQuery = client
    .from(table)
    .select(
      "rank, title, author, publisher, isbn13, url, rank_change, match_status, collected_at, bookstore"
    )
    .eq("bookstore", bookstore)
    .eq("collected_at", collectedAt)
    .order("rank", { ascending: true });
  if (category !== null) {
    rowsQuery = rowsQuery.eq("category", category);
  }

  const { data, error } = await rowsQuery;
  if (error) throw error;
  return { collectedAt, rows: data || [] };
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const scope = searchParams.get("scope");
  const category = searchParams.get("category");
  const at = searchParams.get("at");

  if (!scope || !at) {
    return NextResponse.json(
      { error: "scope, at 파라미터가 필요합니다." },
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

  const storeData = {};
  const errors = {};
  const resolvedAt = {};

  try {
    await Promise.all(
      BOOKSTORES.map(async (bookstore) => {
        try {
          const { collectedAt, rows } = await getSnapshotAtOrBefore(
            client,
            table,
            bookstore,
            categoryValue,
            at
          );
          storeData[bookstore] = rows;
          resolvedAt[bookstore] = collectedAt;
          if (rows.length === 0) {
            errors[bookstore] = "선택한 시점 이전에 수집된 기록이 없습니다.";
          }
        } catch (e) {
          storeData[bookstore] = [];
          errors[bookstore] = String(e.message || e);
        }
      })
    );
  } catch (e) {
    return NextResponse.json({ error: String(e.message || e) }, { status: 500 });
  }

  return NextResponse.json({ storeData, errors, resolvedAt });
}

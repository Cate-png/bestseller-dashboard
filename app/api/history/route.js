import { NextResponse } from "next/server";
import { getSupabaseServerClient } from "../../../lib/supabaseServer";

// 과거 기록 조회 API. 클라이언트(Dashboard.jsx)가 날짜/시간을 선택하면
// 이 라우트를 호출해, 그 시점 "이전(또는 그 시점)의 가장 최근 스냅샷"을
// 서점별로 찾아 반환합니다. Supabase 접속(SUPABASE_SERVICE_KEY)은 항상
// 이 서버 라우트 안에서만 이뤄지고 브라우저로 전달되지 않습니다
// (lib/supabaseServer.js와 동일한 원칙).
//
// scope=total    -> rankings 테이블, category="종합"
// scope=daily    -> rankings 테이블, category="일간" (종합 일간 TOP100)
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

  // cover_url은 rankings 테이블에만 있는 컬럼입니다(sql/rankings_cover_url.sql,
  // "표지 보기" 알라딘 확장, 2026-08-26) - realtime_rankings에는 없어서
  // scope=realtime(table="realtime_rankings")일 때 그대로 select에
  // 넣으면 "column does not exist" 오류가 납니다. table로 분기합니다.
  const rowsSelect =
    table === "rankings"
      ? "rank, title, author, publisher, isbn13, url, rank_change, match_status, collected_at, bookstore, run_id, cover_url"
      : "rank, title, author, publisher, isbn13, url, rank_change, match_status, collected_at, bookstore, run_id";

  let rowsQuery = client
    .from(table)
    .select(rowsSelect)
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

// 종합(주간/일간) 라운드를 만든 run_id로 collection_runs.run_at(각 수집
// 스크립트가 rankings 저장 성공 직후 다시 기록해두는 "실제 DB 저장 완료
// 시각")을 조회합니다. scope=total/daily(=rankings, category="종합"/"일간")
// 일 때만 씁니다 - 분야별/실시간 스크립트는 아직 run_at을 갱신하지 않으므로
// 조회해도 의미가 없습니다.
async function getRunSavedAt(client, runId) {
  if (!runId) return null;
  const { data, error } = await client
    .from("collection_runs")
    .select("run_at")
    .eq("id", runId)
    .limit(1);
  if (error || !data || data.length === 0) return null;
  return data[0].run_at || null;
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
    scope === "total"
      ? "종합"
      : scope === "daily"
      ? "일간"
      : scope === "category"
      ? category
      : null;

  const storeData = {};
  const errors = {};
  const resolvedAt = {};
  const resolvedSavedAt = {};

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
          } else if (scope === "total" || scope === "daily") {
            resolvedSavedAt[bookstore] = await getRunSavedAt(client, rows[0].run_id);
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

  return NextResponse.json({ storeData, errors, resolvedAt, resolvedSavedAt });
}

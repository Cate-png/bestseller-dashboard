import { getSupabaseServerClient } from "../lib/supabaseServer";
import Dashboard from "../components/Dashboard";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BOOKSTORES = ["교보문고", "예스24", "알라딘"];
const CATEGORY = "종합";

async function getLatestSuccessRun(client, bookstore) {
  const { data, error } = await client
    .from("collection_runs")
    .select("id, run_at")
    .eq("bookstore", bookstore)
    .eq("status", "success")
    .order("run_at", { ascending: false })
    .limit(1);

  if (error) throw error;
  return data && data.length > 0 ? data[0] : null;
}

async function getRankingsForRun(client, runId) {
  const { data, error } = await client
    .from("rankings")
    .select(
      "rank, title, author, publisher, isbn13, url, rank_change, match_status, collected_at, bookstore"
    )
    .eq("run_id", runId)
    .order("rank", { ascending: true });

  if (error) throw error;
  return data || [];
}

async function getWindowRows(client, hours) {
  const since = new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
  const { data, error } = await client
    .from("rankings")
    .select("rank, title, author, publisher, isbn13, collected_at, bookstore")
    .eq("category", CATEGORY)
    .gte("collected_at", since)
    .order("collected_at", { ascending: true });

  if (error) throw error;
  return data || [];
}

export default async function Page() {
  let client;
  try {
    client = getSupabaseServerClient();
  } catch (e) {
    return (
      <div style={{ padding: 24 }}>
        <h1>설정 오류</h1>
        <p>{String(e.message || e)}</p>
      </div>
    );
  }

  const storeData = {};
  const errors = {};
  let latestCollectedAt = null;

  for (const bookstore of BOOKSTORES) {
    try {
      const run = await getLatestSuccessRun(client, bookstore);
      if (!run) {
        storeData[bookstore] = [];
        errors[bookstore] = "아직 성공한 수집 기록이 없습니다.";
        continue;
      }
      const rankings = await getRankingsForRun(client, run.id);
      storeData[bookstore] = rankings;
      if (rankings.length > 0) {
        const t = rankings[0].collected_at;
        if (!latestCollectedAt || t > latestCollectedAt) {
          latestCollectedAt = t;
        }
      }
    } catch (e) {
      storeData[bookstore] = [];
      errors[bookstore] = String(e.message || e);
    }
  }

  // 트렌드 분석용: 최근 6시간 / 24시간 구간 원본 데이터 (여러 run_id에 걸쳐 있음)
  let window6h = [];
  let window24h = [];
  try {
    window6h = await getWindowRows(client, 6);
    window24h = await getWindowRows(client, 24);
  } catch (e) {
    // 트렌드 구간 조회가 실패해도 기본 화면은 정상적으로 보여줘야 하므로
    // 여기서는 조용히 빈 배열로 둡니다. (Dashboard 쪽에서 "데이터 부족" 처리)
  }

  return (
    <Dashboard
      bookstores={BOOKSTORES}
      storeData={storeData}
      errors={errors}
      collectedAt={latestCollectedAt}
      window6h={window6h}
      window24h={window24h}
    />
  );
}


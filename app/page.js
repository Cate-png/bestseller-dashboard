import { getSupabaseServerClient } from "../lib/supabaseServer";
import Dashboard from "../components/Dashboard";
import { CATEGORIES } from "../lib/categories";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BOOKSTORES = ["교보문고", "예스24", "알라딘"];
const CATEGORY = "종합";

// 특정 서점 + 분야의 "가장 최근 수집 스냅샷"을 가져옵니다.
// (예전에는 collection_runs에서 "이 서점의 가장 최근 성공한 run"을 먼저 찾은 뒤
// 그 run의 rankings를 전부 가져왔습니다. 분야별(카테고리) 수집이 추가되면서
// "이 서점의 가장 최근 run"이 항상 종합 수집이라는 보장이 없어졌기 때문에,
// rankings에서 bookstore+category로 직접 가장 최근 스냅샷을 찾도록 바꿨습니다.
// category="종합"으로 호출하면 기존 종합 TOP100 조회와 동일하게 동작합니다.)
async function getLatestCategoryRankings(client, bookstore, category) {
  const latest = await client
    .from("rankings")
    .select("collected_at")
    .eq("bookstore", bookstore)
    .eq("category", category)
    .order("collected_at", { ascending: false })
    .limit(1);

  if (latest.error) throw latest.error;
  if (!latest.data || latest.data.length === 0) return [];

  const collectedAt = latest.data[0].collected_at;

  const { data, error } = await client
    .from("rankings")
    .select(
      "rank, title, author, publisher, isbn13, url, rank_change, match_status, collected_at, bookstore"
    )
    .eq("bookstore", bookstore)
    .eq("category", category)
    .eq("collected_at", collectedAt)
    .order("rank", { ascending: true });

  if (error) throw error;
  return data || [];
}

// 실시간 베스트셀러(realtime_rankings)의 "서점별 가장 최근 스냅샷"을 가져옵니다.
// 기존 rankings(주간/분야별)와는 완전히 별개의 테이블이며, category 개념이 없습니다.
async function getLatestRealtimeRankings(client, bookstore) {
  const latest = await client
    .from("realtime_rankings")
    .select("collected_at")
    .eq("bookstore", bookstore)
    .order("collected_at", { ascending: false })
    .limit(1);

  if (latest.error) throw latest.error;
  if (!latest.data || latest.data.length === 0) return [];

  const collectedAt = latest.data[0].collected_at;

  const { data, error } = await client
    .from("realtime_rankings")
    .select(
      "rank, title, author, publisher, isbn13, url, rank_change, match_status, collected_at, bookstore"
    )
    .eq("bookstore", bookstore)
    .eq("collected_at", collectedAt)
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
      const rankings = await getLatestCategoryRankings(client, bookstore, CATEGORY);
      storeData[bookstore] = rankings;
      if (rankings.length === 0) {
        errors[bookstore] = "아직 성공한 수집 기록이 없습니다.";
      } else {
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

  // 분야별 TOP10: 예전에는 14개 분야 x 3개 서점을 페이지 렌더링 시점에
  // 전부 미리 조회해뒀지만(최대 84개 쿼리), 분야가 6개에서 14개로 늘면서
  // 초기 로딩이 눈에 띄게 느려졌습니다. Dashboard.jsx가 어차피 마운트 후
  // 선택된 탭 기준으로 /api/history를 호출해 최신 데이터를 다시 받아오는
  // 구조라 이 프리페치 결과는 화면에 거의 쓰이지 않았습니다(분야 탭으로
  // 진입하는 순간 클라이언트가 곧바로 덮어씀). 그래서 서버에서는 더 이상
  // 분야별 데이터를 조회하지 않고, 분야 탭을 클릭했을 때만 Dashboard.jsx가
  // /api/history?scope=category&category=...를 호출해 그 분야 데이터를
  // 지연 조회(lazy load)하도록 바꿨습니다. categories(분야 이름 목록)는
  // 탭 렌더링에 계속 필요하므로 그대로 넘깁니다.
  const categoryData = {};
  const categoryErrors = {};

  // 실시간 베스트셀러: 기존 주간/분야별 rankings와 완전히 별개인 realtime_rankings에서
  // 서점별 최신 스냅샷만 조회합니다. 이 단계에서는 순위 표시만 하고 트렌드/급상승
  // 분석은 하지 않으므로 window 조회 같은 추가 계산은 하지 않습니다.
  const realtimeData = {};
  const realtimeErrors = {};
  await Promise.all(
    BOOKSTORES.map(async (bookstore) => {
      try {
        const rankings = await getLatestRealtimeRankings(client, bookstore);
        realtimeData[bookstore] = rankings;
        if (rankings.length === 0) {
          realtimeErrors[bookstore] = "아직 성공한 실시간 수집 기록이 없습니다.";
        }
      } catch (e) {
        realtimeData[bookstore] = [];
        realtimeErrors[bookstore] = String(e.message || e);
      }
    })
  );

  // 트렌드 분석용: 최근 6시간 / 24시간 구간 원본 데이터 (여러 run_id에 걸쳐 있음, 종합 기준)
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
      categories={CATEGORIES}
      categoryData={categoryData}
      categoryErrors={categoryErrors}
      realtimeData={realtimeData}
      realtimeErrors={realtimeErrors}
    />
  );
}


// "꾸준한 강세" 계산: 최근 N회(round) 수집에서 TOP20을 얼마나 자주
// 유지했는지 집계합니다.
//
// rows는 app/page.js가 미리 조회해둔, "최근 N회 수집 중 TOP20 이내였던
// 행"만 모아둔 rankings 원본입니다
// ({ bookstore, collected_at, rank, title, author, publisher, isbn13 }).
// 여기서는 순수 계산만 하고 Supabase 조회는 하지 않습니다(app/page.js가
// 기존 rankings 테이블을 그대로 재사용해서 가져옴).
//
// "회차"는 collected_at을 KST 날짜(YYYY-MM-DD)로 뭉쳐서 정의합니다. 3사가
// 같은 collect.yml 워크플로 안에서 매일 함께 수집되지만 각 스크립트가
// 각자 datetime.now()로 자기 시각을 찍기 때문에 정확히 같은 timestamp가
// 아닙니다 - 그래서 "서점별로 독립적인 최신순 순번"을 회차로 쓰면, 특정
// 서점만 하루 수집에 실패해 날짜가 하나 비었을 때 회차가 서로 어긋나
// 버립니다(예: 교보는 7일 전부 있고 예스24는 3일만 있으면, 예스24의
// "1번째 회차"가 실제로는 교보의 "3번째 회차"와 같은 날일 수 있음).
// 날짜 단위로 회차를 정의하면 이런 어긋남 없이 항상 "같은 날 = 같은
// 회차"로 정확히 맞습니다.
//
// 도서 하나가 "이번 회차에 TOP20이었다"는 판정은 3사 중 한 곳이라도 그
// 회차에 TOP20이면 인정합니다(OR) - 다만 여러 서점에서 동시에 유지한
// 도서일수록 관측치가 많아져 평균 순위 계산과 정렬에서 자연히 유리해집니다.
function toKstDateKey(collectedAt) {
  const d = new Date(collectedAt);
  const kst = new Date(d.getTime() + 9 * 60 * 60 * 1000);
  return kst.toISOString().slice(0, 10); // YYYY-MM-DD (KST 기준)
}

export function getSteadyBooks(
  rows,
  { bookstores, totalRounds = 7, minRounds = 5, minHits = 5, limit = 10 } = {}
) {
  const allDateKeys = [...new Set(rows.map((r) => toKstDateKey(r.collected_at)))].sort(
    (a, b) => (a < b ? 1 : a > b ? -1 : 0)
  ); // 최신 날짜가 0번

  const roundsAvailable = Math.min(allDateKeys.length, totalRounds);
  if (roundsAvailable < minRounds) {
    return { books: [], roundsAvailable, insufficientData: true };
  }

  const roundIndexOf = new Map(allDateKeys.map((key, i) => [key, i]));

  const byIsbn = new Map();
  for (const row of rows) {
    if (!row.isbn13) continue;
    const roundIndex = roundIndexOf.get(toKstDateKey(row.collected_at));
    if (roundIndex === undefined || roundIndex >= totalRounds) continue;

    if (!byIsbn.has(row.isbn13)) {
      byIsbn.set(row.isbn13, {
        isbn13: row.isbn13,
        title: row.title,
        author: row.author,
        publisher: row.publisher,
        // 같은 서점 + 같은 회차(날짜) 관측치가 중복으로 들어와 평균이
        // 왜곡되지 않도록 "서점::회차"당 하나만 남깁니다.
        observationByKey: new Map(),
      });
    }
    const key = `${row.bookstore}::${roundIndex}`;
    byIsbn.get(row.isbn13).observationByKey.set(key, {
      bookstore: row.bookstore,
      roundIndex,
      rank: row.rank,
    });
  }

  const result = [];
  for (const book of byIsbn.values()) {
    const observations = [...book.observationByKey.values()];
    const hitCount = new Set(observations.map((o) => o.roundIndex)).size;
    if (hitCount < minHits) continue;

    const avgRank =
      observations.reduce((sum, o) => sum + o.rank, 0) / observations.length;

    const currentObservations = observations.filter((o) => o.roundIndex === 0);
    const currentAvgRank =
      currentObservations.length > 0
        ? currentObservations.reduce((sum, o) => sum + o.rank, 0) / currentObservations.length
        : null;

    const currentRankByStore = {};
    for (const o of currentObservations) currentRankByStore[o.bookstore] = o.rank;

    result.push({
      isbn13: book.isbn13,
      title: book.title,
      author: book.author,
      publisher: book.publisher,
      hitCount,
      avgRank,
      currentAvgRank,
      currentRankByStore,
    });
  }

  // 1순위: TOP20 유지 횟수, 2순위: 전체 평균 순위, 3순위: 현재(최신 회차) 평균 순위.
  result.sort((a, b) => {
    if (b.hitCount !== a.hitCount) return b.hitCount - a.hitCount;
    if (a.avgRank !== b.avgRank) return a.avgRank - b.avgRank;
    const aCur = a.currentAvgRank ?? Infinity;
    const bCur = b.currentAvgRank ?? Infinity;
    return aCur - bCur;
  });

  return { books: result.slice(0, limit), roundsAvailable, insufficientData: false };
}

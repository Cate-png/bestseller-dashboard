// 트렌드 분석 계산 함수들.
// 입력값 allRows는 [{ bookstore, rank, title, author, publisher, isbn13, rank_change, match_status, url }, ...]
// 형태로, 3개 서점의 "최신 스냅샷" 데이터를 합친 배열입니다.
//
// 참고: 여기서 쓰는 rank_change는 각 수집 스크립트가 "바로 직전 성공한 수집"과
// 비교해서 저장해둔 값입니다. 자동화가 매시간 돌기 시작하면 이 값이 곧
// "직전 수집 대비(대략 최근 1회분) 변동"이 됩니다. 지금 당장은 이 값 하나로
// 상승/하락/신규 진입을 계산하고, 6시간/24시간처럼 더 긴 구간 비교는
// getWindowTrend()가 별도의 과거 데이터 조회로 처리합니다 (데이터가 아직
// 많이 쌓이지 않았다면 결과가 적거나 비어있을 수 있습니다).

export function getRisingBooks(allRows, limit = 10) {
  return allRows
    .filter((r) => typeof r.rank_change === "number" && r.rank_change > 0)
    .sort((a, b) => b.rank_change - a.rank_change)
    .slice(0, limit);
}

export function getFallingBooks(allRows, limit = 10) {
  return allRows
    .filter((r) => typeof r.rank_change === "number" && r.rank_change < 0)
    .sort((a, b) => a.rank_change - b.rank_change)
    .slice(0, limit);
}

export function getNewEntries(allRows, limit = 20) {
  // rank_change가 없고(null), isbn13 매칭은 된 도서 = 직전 수집에는 없었던 책
  return allRows
    .filter((r) => r.rank_change === null && r.match_status === "matched")
    .sort((a, b) => a.rank - b.rank)
    .slice(0, limit);
}

export function getSimultaneousRise(allRows, minStores = 2, limit = 20) {
  const byIsbn = new Map();
  for (const row of allRows) {
    if (!row.isbn13) continue;
    if (!byIsbn.has(row.isbn13)) byIsbn.set(row.isbn13, []);
    byIsbn.get(row.isbn13).push(row);
  }

  const result = [];
  for (const [isbn13, rows] of byIsbn.entries()) {
    const risingRows = rows.filter(
      (r) => typeof r.rank_change === "number" && r.rank_change > 0
    );
    if (risingRows.length >= minStores) {
      result.push({
        isbn13,
        title: rows[0].title,
        author: rows[0].author,
        publisher: rows[0].publisher,
        stores: risingRows.map((r) => ({
          bookstore: r.bookstore,
          rank: r.rank,
          rank_change: r.rank_change,
        })),
      });
    }
  }

  return result
    .sort((a, b) => b.stores.length - a.stores.length)
    .slice(0, limit);
}

export function getCommonBooks(allRows, minStores = 2, limit = 20) {
  const byIsbn = new Map();
  for (const row of allRows) {
    if (!row.isbn13) continue;
    if (!byIsbn.has(row.isbn13)) byIsbn.set(row.isbn13, []);
    byIsbn.get(row.isbn13).push(row);
  }

  const result = [];
  for (const [isbn13, rows] of byIsbn.entries()) {
    if (rows.length >= minStores) {
      result.push({
        isbn13,
        title: rows[0].title,
        author: rows[0].author,
        publisher: rows[0].publisher,
        stores: rows.map((r) => ({ bookstore: r.bookstore, rank: r.rank })),
      });
    }
  }

  return result
    .sort((a, b) => b.stores.length - a.stores.length)
    .slice(0, limit);
}

// 구간(예: 24시간) 내 과거 스냅샷들을 이용해 "그 구간 안에서 순위가 가장 많이
// 바뀐 책"을 계산합니다. windowRows는 해당 시간 범위 안의 rankings 원본 행들
// (여러 run_id에 걸쳐 있을 수 있음)을 그대로 넘기면 됩니다.
export function getWindowTrend(windowRows, limit = 10) {
  const byKey = new Map(); // key = bookstore + isbn13
  for (const row of windowRows) {
    if (!row.isbn13) continue;
    const key = `${row.bookstore}::${row.isbn13}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(row);
  }

  const result = [];
  for (const [key, rows] of byKey.entries()) {
    if (rows.length < 2) continue;
    const sorted = [...rows].sort(
      (a, b) => new Date(a.collected_at) - new Date(b.collected_at)
    );
    const first = sorted[0];
    const last = sorted[sorted.length - 1];
    const change = first.rank - last.rank; // 양수면 상승
    if (change === 0) continue;
    result.push({
      bookstore: last.bookstore,
      isbn13: last.isbn13,
      title: last.title,
      author: last.author,
      publisher: last.publisher,
      fromRank: first.rank,
      toRank: last.rank,
      change,
    });
  }

  return result
    .sort((a, b) => Math.abs(b.change) - Math.abs(a.change))
    .slice(0, limit);
}

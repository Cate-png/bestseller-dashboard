// 실시간 베스트셀러 탭 전용 인사이트 계산 함수들.
// 입력값 allRows는 realtimeData(교보문고/예스24/알라딘의 realtime_rankings 최신
// 스냅샷)를 bookstore 태그를 붙여 평평하게(flatten) 합친 배열입니다
// ([{ bookstore, rank, title, author, publisher, isbn13, rank_change,
// match_status, url }, ...]). rankings(주간/분야별) 데이터와는 절대 섞지
// 않고, 항상 realtimeData에서만 만들어진 배열을 넘겨야 합니다.
//
// "NEW"는 DB에 문자열로 저장되지 않고 rank_change === null &&
// match_status === "matched"로만 판별됩니다 (기존 RankChange 컴포넌트,
// lib/trends.js의 getNewEntries와 동일한 규칙).

// 1) 🔥 지금 치고 올라오는 책: rank_change >= 20인 개별 행을 rank_change 내림차순으로.
export function getRealtimeSurgingBooks(allRows, limit = 5) {
  return allRows
    .filter((r) => typeof r.rank_change === "number" && r.rank_change >= 20)
    .sort((a, b) => b.rank_change - a.rank_change)
    .slice(0, limit);
}

// 2) 📈 여러 서점에서 동시에 상승 중: 같은 isbn13이 2개 이상 서점에서
// rank_change > 0이면 후보. 카드에는 그 책이 등장한 모든 서점의 현재 순위/등락을
// 보여주되(상승하지 않은 서점 포함), "총 상승폭"은 상승한 서점의 rank_change만
// 합산합니다(하락/보합/NEW는 합산에서 제외).
export function getRealtimeSimultaneousRise(allRows, minStores = 2, limit = 5) {
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
    if (risingRows.length < minStores) continue;

    const totalRise = risingRows.reduce((sum, r) => sum + r.rank_change, 0);
    result.push({
      isbn13,
      title: rows[0].title,
      author: rows[0].author,
      publisher: rows[0].publisher,
      totalRise,
      stores: rows.map((r) => ({
        bookstore: r.bookstore,
        rank: r.rank,
        rank_change: r.rank_change,
        match_status: r.match_status,
      })),
    });
  }

  return result.sort((a, b) => b.totalRise - a.totalRise).slice(0, limit);
}

// 3) 🆕 새롭게 등장한 책: rank_change===null && match_status==="matched"인 행을
// isbn13 기준으로 묶어(여러 서점에서 동시에 NEW일 수 있음) "NEW인 서점 목록"을
// 만듭니다. 정렬은 NEW 서점 수 내림차순, 동률이면 그중 최고 순위(낮은 숫자) 오름차순.
export function getRealtimeNewEntries(allRows, limit = 5) {
  const newRows = allRows.filter(
    (r) => r.rank_change === null && r.match_status === "matched"
  );

  const byIsbn = new Map();
  for (const row of newRows) {
    const key = row.isbn13 || `${row.bookstore}::${row.title}`;
    if (!byIsbn.has(key)) byIsbn.set(key, []);
    byIsbn.get(key).push(row);
  }

  const result = [...byIsbn.values()].map((rows) => {
    const bestRank = Math.min(...rows.map((r) => r.rank));
    return {
      isbn13: rows[0].isbn13,
      title: rows[0].title,
      author: rows[0].author,
      publisher: rows[0].publisher,
      bestRank,
      stores: rows.map((r) => ({ bookstore: r.bookstore, rank: r.rank })),
    };
  });

  return result
    .sort((a, b) => {
      if (b.stores.length !== a.stores.length) return b.stores.length - a.stores.length;
      return a.bestRank - b.bestRank;
    })
    .slice(0, limit);
}

// 4) 🔍 급상승 출판사·저자·키워드: 화면에 보이는 상위 5권(getRealtimeSurgingBooks의
// limit)이 아니라, rank_change >= 20인 전체 급상승 집합을 기준으로 집계합니다.
// 출판사/저자는 급상승 도서가 2권 이상 겹칠 때만 후보로 인정합니다.
export function getRealtimeSurgeAggregates(allRows) {
  const surgeRows = allRows.filter(
    (r) => typeof r.rank_change === "number" && r.rank_change >= 20
  );

  const byPublisher = new Map();
  const byAuthor = new Map();
  for (const row of surgeRows) {
    const publisher = (row.publisher || "").trim();
    if (publisher) {
      if (!byPublisher.has(publisher)) byPublisher.set(publisher, []);
      byPublisher.get(publisher).push(row);
    }
    const authors = (row.author || "")
      .split(/[,/]/)
      .map((a) => a.trim())
      .filter((a) => a.length >= 2);
    for (const author of authors) {
      if (!byAuthor.has(author)) byAuthor.set(author, []);
      byAuthor.get(author).push(row);
    }
  }

  const toRankedList = (map) =>
    [...map.entries()]
      .filter(([, rows]) => rows.length >= 2)
      .map(([name, rows]) => ({
        name,
        count: rows.length,
        totalRise: rows.reduce((sum, r) => sum + r.rank_change, 0),
      }))
      .sort((a, b) => b.totalRise - a.totalRise || b.count - a.count);

  return {
    publishers: toRankedList(byPublisher),
    authors: toRankedList(byAuthor),
    surgeRows,
  };
}

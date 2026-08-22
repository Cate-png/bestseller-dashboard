"use client";

import { useMemo, useState } from "react";
import { isWisdomHouse } from "../lib/wisdomhouse";
import {
  getRisingBooks,
  getFallingBooks,
  getNewEntries,
  getSimultaneousRise,
  getCommonBooks,
  getWindowTrend,
} from "../lib/trends";
import {
  buildUniqueBooks,
  extractTrendKeywords,
  extractNotableFlows,
} from "../lib/insights";
import {
  getRealtimeSurgingBooks,
  getRealtimeSimultaneousRise,
  getRealtimeNewEntries,
  getRealtimeSurgeAggregates,
} from "../lib/realtimeInsights";

const COLUMN_CLASS = {
  교보문고: "kyobo",
  예스24: "yes24",
  알라딘: "aladin",
};

function formatDateTime(iso) {
  if (!iso) return "데이터 없음";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())} 기준`;
}

// lib/trends.js가 이미 계산해 둔 결과(rising/falling/newEntries/trend6h/
// trend24h)를 bookstore 필드로만 나누는 순수 표시용 그룹화입니다. 새로운
// 집계/계산은 하지 않고, 각 서점 목록 안의 항목·순서·값은 그대로 유지합니다.
function groupRowsByStore(rows, bookstores) {
  const byStore = {};
  for (const bookstore of bookstores) {
    byStore[bookstore] = rows.filter((r) => r.bookstore === bookstore);
  }
  return byStore;
}

function matchesSearch(row, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    (row.title || "").toLowerCase().includes(q) ||
    (row.author || "").toLowerCase().includes(q) ||
    (row.publisher || "").toLowerCase().includes(q) ||
    (row.isbn13 || "").toLowerCase().includes(q)
  );
}

function RankChange({ rankChange, matchStatus }) {
  if (typeof rankChange === "number" && rankChange > 0) {
    return <span className="rank-change up">↑{rankChange}</span>;
  }
  if (typeof rankChange === "number" && rankChange < 0) {
    return <span className="rank-change down">↓{Math.abs(rankChange)}</span>;
  }
  if (rankChange === 0) {
    return <span className="rank-change flat">-</span>;
  }
  if (matchStatus === "matched") {
    return <span className="rank-change new">NEW</span>;
  }
  return <span className="rank-change flat">-</span>;
}

// 실시간 탭에서만 20위 이상 급상승(rank_change >= 20) 도서의 제목을
// 볼드 처리하고 🔥를 붙여 표시하기 위한 플래그. 다른 탭(종합/분야별)에는
// highlightSurge를 넘기지 않으므로 기존 표시 방식 그대로 유지됩니다.
function BookRow({ row, highlightSurge }) {
  const wisdom = isWisdomHouse(row.publisher);
  const isSurge =
    highlightSurge && typeof row.rank_change === "number" && row.rank_change >= 20;
  const titleClass = `book-title${wisdom ? " wisdom-title" : ""}${
    isSurge ? " surge-title" : ""
  }`;
  const titleContent = (
    <>
      {wisdom && <span className="wisdom-badge">위즈덤</span>}
      {isSurge && (
        <span className="surge-emoji" aria-hidden="true">
          🔥
        </span>
      )}
      {row.title}
    </>
  );
  return (
    <div className={`book-row${wisdom ? " wisdom" : ""}`}>
      <div className="rank">{row.rank}</div>
      <div className="book-info">
        {row.url ? (
          <a className={titleClass} href={row.url} target="_blank" rel="noopener noreferrer">
            {titleContent}
          </a>
        ) : (
          <span className={titleClass}>{titleContent}</span>
        )}
        <div className="book-sub">
          {row.author || "저자 미상"} · {row.publisher || "출판사 미상"}
        </div>
      </div>
      <RankChange rankChange={row.rank_change} matchStatus={row.match_status} />
    </div>
  );
}

// highlightSurge: 실시간 탭에서 BookColumn을 렌더링할 때만 true로 넘겨,
// 20위 이상 급상승 도서를 BookRow에서 강조 표시하게 합니다. 종합/분야별
// 탭은 이 prop을 넘기지 않으므로 기존 표시 방식 그대로 유지됩니다.
//
// collapsible: 종합/분야별(주간 베스트셀러) 탭에서만 true로 넘겨, 모바일
// 화면에서 서점 헤더를 눌러 그 서점의 목록만 접었다 펼 수 있게 합니다.
// 실시간 탭에는 이 prop을 넘기지 않으므로(collapsible=false) 기존 UI가
// 그대로 유지됩니다. 접힘 여부는 CSS(.column.collapsed .book-list)로만
// 숨기고 모바일 media query 안에서만 적용되므로, 데스크톱에서는 접혀 있는
// 상태여도 항상 목록이 그대로 보입니다(기존 3열 레이아웃 유지).
function BookColumn({
  bookstore,
  rows,
  error,
  query,
  onlyWisdom,
  highlightSurge,
  collapsible,
}) {
  const [collapsed, setCollapsed] = useState(false);
  const visibleRows = rows.filter(
    (r) => matchesSearch(r, query) && (!onlyWisdom || isWisdomHouse(r.publisher))
  );

  const headerLabel = (
    <>
      {bookstore}{" "}
      <span className="column-count">
        ({visibleRows.length}/{rows.length})
      </span>
    </>
  );

  return (
    <div className={`column${collapsible && collapsed ? " collapsed" : ""}`}>
      {collapsible ? (
        <button
          type="button"
          className={`column-header column-header-toggle ${COLUMN_CLASS[bookstore] || ""}`}
          onClick={() => setCollapsed((v) => !v)}
          aria-expanded={!collapsed}
        >
          <span>{headerLabel}</span>
          <span className="column-toggle-icon" aria-hidden="true">
            ▾
          </span>
        </button>
      ) : (
        <div className={`column-header ${COLUMN_CLASS[bookstore] || ""}`}>
          {headerLabel}
        </div>
      )}
      <div className="book-list">
        {error && rows.length === 0 && (
          <div style={{ padding: 12, fontSize: 13, color: "#a00" }}>{error}</div>
        )}
        {rows.length > 0 && visibleRows.length === 0 && (
          <div style={{ padding: 12, fontSize: 13, color: "#999" }}>
            조건에 맞는 도서가 없습니다.
          </div>
        )}
        {visibleRows.map((row) => (
          <BookRow
            key={`${bookstore}-${row.rank}`}
            row={row}
            highlightSurge={highlightSurge}
          />
        ))}
      </div>
    </div>
  );
}

function TrendCard({ title, children, className = "" }) {
  return (
    <div className={`trend-card${className ? ` ${className}` : ""}`}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

const TOTAL_CATEGORY = "종합";
const REALTIME_TAB = "실시간 베스트셀러";

export default function Dashboard({
  bookstores,
  storeData,
  errors,
  collectedAt,
  window6h,
  window24h,
  categories = [],
  categoryData = {},
  categoryErrors = {},
  realtimeData = {},
  realtimeErrors = {},
}) {
  const [query, setQuery] = useState("");
  const [onlyWisdom, setOnlyWisdom] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState(TOTAL_CATEGORY);

  const tabs = useMemo(
    () => [TOTAL_CATEGORY, ...categories, REALTIME_TAB],
    [categories]
  );
  const isTotal = selectedCategory === TOTAL_CATEGORY;
  const isRealtime = selectedCategory === REALTIME_TAB;

  const activeStoreData = isRealtime
    ? realtimeData
    : isTotal
    ? storeData
    : categoryData[selectedCategory] || {};
  const activeErrors = isRealtime
    ? realtimeErrors
    : isTotal
    ? errors
    : categoryErrors[selectedCategory] || {};

  const activeCollectedAt = useMemo(() => {
    if (isTotal) return collectedAt;
    let latest = null;
    for (const bookstore of bookstores) {
      const rows = activeStoreData[bookstore] || [];
      if (rows.length > 0) {
        const t = rows[0].collected_at;
        if (!latest || t > latest) latest = t;
      }
    }
    return latest;
  }, [isTotal, collectedAt, activeStoreData, bookstores]);

  const allRows = useMemo(() => {
    const merged = [];
    for (const bookstore of bookstores) {
      for (const row of storeData[bookstore] || []) {
        merged.push({ ...row, bookstore });
      }
    }
    return merged;
  }, [bookstores, storeData]);

  const rising = useMemo(() => getRisingBooks(allRows, 10), [allRows]);
  const falling = useMemo(() => getFallingBooks(allRows, 10), [allRows]);
  const newEntries = useMemo(() => getNewEntries(allRows, 10), [allRows]);
  const simultaneousRise = useMemo(
    () => getSimultaneousRise(allRows, 2, 10),
    [allRows]
  );
  const commonBooks = useMemo(() => getCommonBooks(allRows, 2, 10), [allRows]);
  const trend6h = useMemo(() => getWindowTrend(window6h || [], 10), [window6h]);
  const trend24h = useMemo(
    () => getWindowTrend(window24h || [], 10),
    [window24h]
  );

  // 종합 탭 하단 트렌드 카드를 실시간 탭과 동일한 서점별 3열 구조로 보여주기
  // 위한 표시 전용 그룹화. rising/falling/newEntries/trend6h/trend24h 자체의
  // 계산(lib/trends.js)은 그대로이고, 이미 계산된 결과를 bookstore로 나누기만
  // 합니다.
  const risingByStore = useMemo(
    () => groupRowsByStore(rising, bookstores),
    [rising, bookstores]
  );
  const fallingByStore = useMemo(
    () => groupRowsByStore(falling, bookstores),
    [falling, bookstores]
  );
  const newEntriesByStore = useMemo(
    () => groupRowsByStore(newEntries, bookstores),
    [newEntries, bookstores]
  );
  const trend6hByStore = useMemo(
    () => groupRowsByStore(trend6h, bookstores),
    [trend6h, bookstores]
  );
  const trend24hByStore = useMemo(
    () => groupRowsByStore(trend24h, bookstores),
    [trend24h, bookstores]
  );

  const activeUniqueBooks = useMemo(
    () => buildUniqueBooks(activeStoreData, bookstores),
    [activeStoreData, bookstores]
  );
  const trendKeywords = useMemo(
    () => extractTrendKeywords(activeUniqueBooks, 10),
    [activeUniqueBooks]
  );
  const notableFlows = useMemo(
    () => extractNotableFlows(activeUniqueBooks, 3),
    [activeUniqueBooks]
  );

  // 실시간 탭 전용 인사이트: realtimeData만 사용하고(rankings/categoryData와
  // 섞지 않음), storeData 기반 allRows와는 완전히 별개의 배열입니다.
  const realtimeAllRows = useMemo(() => {
    const merged = [];
    for (const bookstore of bookstores) {
      for (const row of realtimeData[bookstore] || []) {
        merged.push({ ...row, bookstore });
      }
    }
    return merged;
  }, [bookstores, realtimeData]);

  // 서점별 그룹핑 표시를 위해 계산 로직(필터/정렬)은 그대로 둔 채, 서점별로
  // 나눈 부분집합에 동일한 함수를 그대로 적용합니다(realtimeInsights.js는
  // 수정하지 않음).
  const realtimeSurgingByStore = useMemo(() => {
    const byStore = {};
    for (const bookstore of bookstores) {
      byStore[bookstore] = getRealtimeSurgingBooks(
        realtimeAllRows.filter((r) => r.bookstore === bookstore),
        5
      );
    }
    return byStore;
  }, [realtimeAllRows, bookstores]);
  const realtimeSimultaneousRise = useMemo(
    () => getRealtimeSimultaneousRise(realtimeAllRows, 2, 5),
    [realtimeAllRows]
  );
  const realtimeNewEntriesByStore = useMemo(() => {
    const byStore = {};
    for (const bookstore of bookstores) {
      byStore[bookstore] = getRealtimeNewEntries(
        realtimeAllRows.filter((r) => r.bookstore === bookstore),
        5
      );
    }
    return byStore;
  }, [realtimeAllRows, bookstores]);
  const realtimeSurgeAggregates = useMemo(
    () => getRealtimeSurgeAggregates(realtimeAllRows),
    [realtimeAllRows]
  );
  const realtimeSurgeKeywords = useMemo(
    () => extractTrendKeywords(realtimeSurgeAggregates.surgeRows, 5),
    [realtimeSurgeAggregates]
  );

  return (
    <div className="page-shell">
      <div className="header">
        <img src="/logo.png" alt="위즈덤하우스" className="brand-logo" />
        <h1>{isRealtime ? "실시간 베스트셀러 현황" : "주간 베스트셀러 현황"}</h1>
        <div className="meta">{isRealtime ? "매시간 갱신" : "매일 오전 6시 갱신"}</div>
        <div className="meta">{formatDateTime(activeCollectedAt)}</div>
        <div className="category-tabs">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={`category-tab${selectedCategory === tab ? " active" : ""}`}
              onClick={() => setSelectedCategory(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="controls">
          <input
            type="text"
            placeholder="도서명 / 저자 / 출판사 / ISBN13 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            className={onlyWisdom ? "active" : ""}
            onClick={() => setOnlyWisdom((v) => !v)}
          >
            위즈덤하우스만 보기
          </button>
          {(query || onlyWisdom) && (
            <button
              onClick={() => {
                setQuery("");
                setOnlyWisdom(false);
              }}
            >
              초기화
            </button>
          )}
        </div>
      </div>

      {Object.keys(activeErrors).length > 0 && (
        <div className="error-banner">
          {Object.entries(activeErrors)
            .map(([store, msg]) => `${store}: ${msg}`)
            .join("  ·  ")}
        </div>
      )}

      <div className="columns">
        {bookstores.map((bookstore) => (
          <BookColumn
            key={bookstore}
            bookstore={bookstore}
            rows={activeStoreData[bookstore] || []}
            error={activeErrors[bookstore]}
            query={query}
            onlyWisdom={onlyWisdom}
            highlightSurge={isRealtime}
            collapsible={!isRealtime}
          />
        ))}
      </div>

      {isTotal && (
      <div className="trend-section">
        <h2>트렌드 분석 (TOP100 전체 기준)</h2>
        <div className="trend-grid">
          <TrendCard title="급상승 도서 (직전 수집 대비)" className="trend-card-wide">
            {rising.length === 0 ? (
              <p className="trend-empty">데이터가 부족합니다.</p>
            ) : (
              <div className="realtime-store-columns">
                {bookstores.map((bookstore) => (
                  <div className="realtime-store-column" key={bookstore}>
                    <div
                      className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}
                    >
                      {bookstore}
                    </div>
                    {(risingByStore[bookstore] || []).length === 0 ? (
                      <p className="trend-empty">데이터가 부족합니다.</p>
                    ) : (
                      <ul>
                        {risingByStore[bookstore].map((r) => (
                          <li key={`${r.bookstore}-${r.isbn13}-rise`}>
                            {r.title} (↑{r.rank_change}, {r.rank}위)
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TrendCard>

          <TrendCard title="급락 도서 (직전 수집 대비)" className="trend-card-wide">
            {falling.length === 0 ? (
              <p className="trend-empty">데이터가 부족합니다.</p>
            ) : (
              <div className="realtime-store-columns">
                {bookstores.map((bookstore) => (
                  <div className="realtime-store-column" key={bookstore}>
                    <div
                      className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}
                    >
                      {bookstore}
                    </div>
                    {(fallingByStore[bookstore] || []).length === 0 ? (
                      <p className="trend-empty">데이터가 부족합니다.</p>
                    ) : (
                      <ul>
                        {fallingByStore[bookstore].map((r) => (
                          <li key={`${r.bookstore}-${r.isbn13}-fall`}>
                            {r.title} (↓{Math.abs(r.rank_change)}, {r.rank}위)
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TrendCard>

          <TrendCard title="신규 진입 도서" className="trend-card-wide">
            {newEntries.length === 0 ? (
              <p className="trend-empty">데이터가 부족합니다.</p>
            ) : (
              <div className="realtime-store-columns">
                {bookstores.map((bookstore) => (
                  <div className="realtime-store-column" key={bookstore}>
                    <div
                      className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}
                    >
                      {bookstore}
                    </div>
                    {(newEntriesByStore[bookstore] || []).length === 0 ? (
                      <p className="trend-empty">데이터가 부족합니다.</p>
                    ) : (
                      <ul>
                        {newEntriesByStore[bookstore].map((r) => (
                          <li key={`${r.bookstore}-${r.isbn13}-new`}>
                            {r.title} ({r.rank}위)
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TrendCard>

          <TrendCard title="여러 서점에서 동시 상승">
            {simultaneousRise.length === 0 ? (
              <p className="trend-empty">해당하는 도서가 없습니다.</p>
            ) : (
              <ul>
                {simultaneousRise.map((b) => (
                  <li key={b.isbn13}>
                    {b.title} —{" "}
                    {b.stores
                      .map((s) => `${s.bookstore} ↑${s.rank_change}`)
                      .join(", ")}
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>

          <TrendCard title="여러 서점 TOP100 공통 등장">
            {commonBooks.length === 0 ? (
              <p className="trend-empty">해당하는 도서가 없습니다.</p>
            ) : (
              <ul>
                {commonBooks.map((b) => (
                  <li key={b.isbn13}>
                    {b.title} —{" "}
                    {b.stores.map((s) => `${s.bookstore} ${s.rank}위`).join(", ")}
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>

          <TrendCard title="최근 6시간 순위 변화" className="trend-card-wide">
            {trend6h.length === 0 ? (
              <p className="trend-empty">
                아직 6시간 범위의 비교 데이터가 충분하지 않습니다. (수집이 반복될수록
                채워집니다)
              </p>
            ) : (
              <div className="realtime-store-columns">
                {bookstores.map((bookstore) => (
                  <div className="realtime-store-column" key={bookstore}>
                    <div
                      className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}
                    >
                      {bookstore}
                    </div>
                    {(trend6hByStore[bookstore] || []).length === 0 ? (
                      <p className="trend-empty">데이터가 부족합니다.</p>
                    ) : (
                      <ul>
                        {trend6hByStore[bookstore].map((r, i) => (
                          <li key={i}>
                            {r.title} ({r.fromRank}위 → {r.toRank}위,{" "}
                            {r.change > 0 ? `↑${r.change}` : `↓${Math.abs(r.change)}`})
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TrendCard>

          <TrendCard title="최근 24시간 순위 변화" className="trend-card-wide">
            {trend24h.length === 0 ? (
              <p className="trend-empty">
                아직 24시간 범위의 비교 데이터가 충분하지 않습니다. (수집이 반복될수록
                채워집니다)
              </p>
            ) : (
              <div className="realtime-store-columns">
                {bookstores.map((bookstore) => (
                  <div className="realtime-store-column" key={bookstore}>
                    <div
                      className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}
                    >
                      {bookstore}
                    </div>
                    {(trend24hByStore[bookstore] || []).length === 0 ? (
                      <p className="trend-empty">데이터가 부족합니다.</p>
                    ) : (
                      <ul>
                        {trend24hByStore[bookstore].map((r, i) => (
                          <li key={i}>
                            {r.title} ({r.fromRank}위 → {r.toRank}위,{" "}
                            {r.change > 0 ? `↑${r.change}` : `↓${Math.abs(r.change)}`})
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            )}
          </TrendCard>
        </div>
      </div>
      )}

      {!isRealtime && (
      <div className="insight-section">
        <h2>트렌드 키워드</h2>
        {trendKeywords.length === 0 ? (
          <p className="trend-empty">
            아직 두드러진 키워드가 없습니다. (겹치는 표현이 2권 이상일 때
            표시됩니다)
          </p>
        ) : (
          <div className="keyword-list">
            {trendKeywords.map(({ keyword, bookCount }) => (
              <span className="keyword-chip" key={keyword}>
                {keyword} <span className="keyword-count">{bookCount}권</span>
              </span>
            ))}
          </div>
        )}

        <h2 className="insight-subheading">주목할 흐름</h2>
        {notableFlows.length === 0 ? (
          <p className="trend-empty">아직 눈에 띄는 흐름이 없습니다.</p>
        ) : (
          <ul className="flow-list">
            {notableFlows.map((flow, i) => (
              <li key={i}>
                {flow.description}
                <span className="flow-count">{flow.bookCount}권</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      )}

      {isRealtime && (
      <div className="realtime-insight-section">
        <h2>실시간 트렌드</h2>
        <div className="realtime-insight-stack">
          <div className="realtime-insight-card realtime-insight-card-wide">
            <h3>🔥 지금 치고 올라오는 책</h3>
            <div className="realtime-store-columns">
              {bookstores.map((bookstore) => (
                <div className="realtime-store-column" key={bookstore}>
                  <div className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}>
                    {bookstore}
                  </div>
                  {(realtimeSurgingByStore[bookstore] || []).length === 0 ? (
                    <p className="trend-empty">아직 20위 이상 상승한 도서가 없습니다.</p>
                  ) : (
                    <ul>
                      {realtimeSurgingByStore[bookstore].map((r) => (
                        <li key={`${bookstore}-${r.isbn13 || r.title}-surge`}>
                          {r.title}
                          <span className="realtime-insight-sub">
                            {" "}
                            — {r.author || "저자 미상"} · {r.publisher || "출판사 미상"}
                          </span>
                          <span className="realtime-insight-meta">
                            {" "}
                            (현재 {r.rank}위, ▲{r.rank_change})
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="realtime-insight-card realtime-insight-card-wide">
            <h3>📈 여러 서점에서 동시에 상승 중</h3>
            {realtimeSimultaneousRise.length === 0 ? (
              <p className="trend-empty">2개 이상 서점에서 동시에 상승 중인 도서가 없습니다.</p>
            ) : (
              <ul>
                {realtimeSimultaneousRise.map((b) => (
                  <li key={b.isbn13}>
                    {b.title}
                    <span className="realtime-insight-meta"> (총 상승폭 ▲{b.totalRise})</span>
                    <br />
                    <span className="realtime-insight-sub">
                      {b.stores
                        .map((s) => {
                          const change =
                            typeof s.rank_change === "number"
                              ? s.rank_change > 0
                                ? `▲${s.rank_change}`
                                : s.rank_change < 0
                                ? `▼${Math.abs(s.rank_change)}`
                                : "-"
                              : s.match_status === "matched"
                              ? "NEW"
                              : "-";
                          return `${s.bookstore} ${s.rank}위(${change})`;
                        })
                        .join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="realtime-insight-card realtime-insight-card-wide">
            <h3>🆕 새롭게 등장한 책</h3>
            <div className="realtime-store-columns">
              {bookstores.map((bookstore) => (
                <div className="realtime-store-column" key={bookstore}>
                  <div className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}>
                    {bookstore}
                  </div>
                  {(realtimeNewEntriesByStore[bookstore] || []).length === 0 ? (
                    <p className="trend-empty">새롭게 등장한 도서가 없습니다.</p>
                  ) : (
                    <ul>
                      {realtimeNewEntriesByStore[bookstore].map((b) => (
                        <li key={b.isbn13 || b.title}>
                          {b.title}
                          <span className="realtime-insight-meta"> (현재 {b.bestRank}위)</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="realtime-insight-card realtime-insight-card-wide">
            <h3>🔍 급상승 출판사 · 저자 · 키워드</h3>
            <div className="realtime-insight-subheading">출판사</div>
            {realtimeSurgeAggregates.publishers.length === 0 ? (
              <p className="trend-empty">2권 이상 겹치는 출판사가 없습니다.</p>
            ) : (
              <ul>
                {realtimeSurgeAggregates.publishers.slice(0, 5).map((p) => (
                  <li key={`publisher-${p.name}`}>
                    {p.name}
                    <span className="realtime-insight-meta">
                      {" "}
                      ({p.count}권, 총 상승폭 ▲{p.totalRise})
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="realtime-insight-subheading">저자</div>
            {realtimeSurgeAggregates.authors.length === 0 ? (
              <p className="trend-empty">2권 이상 겹치는 저자가 없습니다.</p>
            ) : (
              <ul>
                {realtimeSurgeAggregates.authors.slice(0, 5).map((a) => (
                  <li key={`author-${a.name}`}>
                    {a.name}
                    <span className="realtime-insight-meta">
                      {" "}
                      ({a.count}권, 총 상승폭 ▲{a.totalRise})
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="realtime-insight-subheading">키워드</div>
            {realtimeSurgeKeywords.length === 0 ? (
              <p className="trend-empty">두드러진 키워드가 없습니다.</p>
            ) : (
              <div className="keyword-list">
                {realtimeSurgeKeywords.map(({ keyword, bookCount }) => (
                  <span className="keyword-chip" key={`realtime-kw-${keyword}`}>
                    {keyword} <span className="keyword-count">{bookCount}권</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      )}
    </div>
  );
}

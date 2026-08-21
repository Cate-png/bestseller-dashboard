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

function BookRow({ row }) {
  const wisdom = isWisdomHouse(row.publisher);
  return (
    <div className={`book-row${wisdom ? " wisdom" : ""}`}>
      <div className="rank">{row.rank}</div>
      <div className="book-info">
        {row.url ? (
          <a
            className={`book-title${wisdom ? " wisdom-title" : ""}`}
            href={row.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {wisdom && <span className="wisdom-badge">위즈덤</span>}
            {row.title}
          </a>
        ) : (
          <span className={`book-title${wisdom ? " wisdom-title" : ""}`}>
            {wisdom && <span className="wisdom-badge">위즈덤</span>}
            {row.title}
          </span>
        )}
        <div className="book-sub">
          {row.author || "저자 미상"} · {row.publisher || "출판사 미상"}
        </div>
      </div>
      <RankChange rankChange={row.rank_change} matchStatus={row.match_status} />
    </div>
  );
}

function BookColumn({ bookstore, rows, error, query, onlyWisdom }) {
  const visibleRows = rows.filter(
    (r) => matchesSearch(r, query) && (!onlyWisdom || isWisdomHouse(r.publisher))
  );

  return (
    <div className="column">
      <div className={`column-header ${COLUMN_CLASS[bookstore] || ""}`}>
        {bookstore}{" "}
        <span className="column-count">
          ({visibleRows.length}/{rows.length})
        </span>
      </div>
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
          <BookRow key={`${bookstore}-${row.rank}`} row={row} />
        ))}
      </div>
    </div>
  );
}

function TrendCard({ title, children }) {
  return (
    <div className="trend-card">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

const TOTAL_CATEGORY = "종합";

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
}) {
  const [query, setQuery] = useState("");
  const [onlyWisdom, setOnlyWisdom] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState(TOTAL_CATEGORY);

  const tabs = useMemo(() => [TOTAL_CATEGORY, ...categories], [categories]);
  const isTotal = selectedCategory === TOTAL_CATEGORY;

  const activeStoreData = isTotal ? storeData : categoryData[selectedCategory] || {};
  const activeErrors = isTotal ? errors : categoryErrors[selectedCategory] || {};

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

  return (
    <div className="page-shell">
      <div className="header">
        <h1>[위즈덤하우스] 베스트셀러 현황</h1>
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
          />
        ))}
      </div>

      {isTotal && (
      <div className="trend-section">
        <h2>트렌드 분석 (TOP100 전체 기준)</h2>
        <div className="trend-grid">
          <TrendCard title="급상승 도서 (직전 수집 대비)">
            {rising.length === 0 ? (
              <p className="trend-empty">데이터가 부족합니다.</p>
            ) : (
              <ul>
                {rising.map((r) => (
                  <li key={`${r.bookstore}-${r.isbn13}-rise`}>
                    [{r.bookstore}] {r.title} (↑{r.rank_change}, {r.rank}위)
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>

          <TrendCard title="급락 도서 (직전 수집 대비)">
            {falling.length === 0 ? (
              <p className="trend-empty">데이터가 부족합니다.</p>
            ) : (
              <ul>
                {falling.map((r) => (
                  <li key={`${r.bookstore}-${r.isbn13}-fall`}>
                    [{r.bookstore}] {r.title} (↓{Math.abs(r.rank_change)}, {r.rank}
                    위)
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>

          <TrendCard title="신규 진입 도서">
            {newEntries.length === 0 ? (
              <p className="trend-empty">데이터가 부족합니다.</p>
            ) : (
              <ul>
                {newEntries.map((r) => (
                  <li key={`${r.bookstore}-${r.isbn13}-new`}>
                    [{r.bookstore}] {r.title} ({r.rank}위)
                  </li>
                ))}
              </ul>
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

          <TrendCard title="최근 6시간 순위 변화">
            {trend6h.length === 0 ? (
              <p className="trend-empty">
                아직 6시간 범위의 비교 데이터가 충분하지 않습니다. (수집이 반복될수록
                채워집니다)
              </p>
            ) : (
              <ul>
                {trend6h.map((r, i) => (
                  <li key={i}>
                    [{r.bookstore}] {r.title} ({r.fromRank}위 → {r.toRank}위,{" "}
                    {r.change > 0 ? `↑${r.change}` : `↓${Math.abs(r.change)}`})
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>

          <TrendCard title="최근 24시간 순위 변화">
            {trend24h.length === 0 ? (
              <p className="trend-empty">
                아직 24시간 범위의 비교 데이터가 충분하지 않습니다. (수집이 반복될수록
                채워집니다)
              </p>
            ) : (
              <ul>
                {trend24h.map((r, i) => (
                  <li key={i}>
                    [{r.bookstore}] {r.title} ({r.fromRank}위 → {r.toRank}위,{" "}
                    {r.change > 0 ? `↑${r.change}` : `↓${Math.abs(r.change)}`})
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>
        </div>
      </div>
      )}
    </div>
  );
}

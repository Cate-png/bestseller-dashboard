"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { isWisdomHouse } from "../lib/wisdomhouse";
import {
  getRisingBooks,
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
} from "../lib/realtimeInsights";
import RankHistoryChart from "./RankHistoryChart";

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

// 날짜(YYYY-MM-DD, <input type="date"> 값)를 "그 날짜의 마지막 순간(UTC
// 23:59:59.999)"의 ISO 문자열로 바꿉니다. 과거 기록 조회에서 "이 날짜 이전
// 가장 최근 스냅샷"을 찾을 때 상한선으로 씁니다(정확한 타임존 보정 없이
// 날짜 단위로만 판단하는 단순한 방식입니다).
function endOfDayISO(dateStr) {
  return new Date(`${dateStr}T23:59:59.999Z`).toISOString();
}

// 날짜 + 시(0~23, "00"~"23")를 "그 시간대의 마지막 순간(UTC HH:59:59.999)"의
// ISO 문자열로 바꿉니다. 실시간 수집은 매시 정각에 트리거되지만 실제 저장
// 시각은 몇 분씩 밀릴 수 있어(예: 14시 수집이 14:03에 완료), 상한을 정확히
// "HH:00:00"으로 두면 그 시간대 스냅샷을 놓치고 한 시간 전으로 밀려날 수
// 있습니다. endOfDayISO와 동일한 방식(정확한 타임존 보정 없이 시 단위로만
// 판단)으로 그 시간의 끝을 상한으로 써서, api/history의 "이 시각 이전 가장
// 최근 스냅샷" 조회가 사용자가 고른 시(H)의 스냅샷을 정확히 찾게 합니다.
function endOfHourISO(dateStr, hourStr) {
  return new Date(`${dateStr}T${hourStr}:59:59.999Z`).toISOString();
}

// 브라우저의 현재 로컬 날짜/시를 <input type="date"> 값 형식(YYYY-MM-DD)과
// 시 선택 드롭다운 값 형식("00"~"23")으로 각각 반환합니다. 서버 렌더링
// 시점과 클라이언트 하이드레이션 시점의 값이 다를 수 있어(hydration
// mismatch) useEffect 안에서 마운트 후에만 호출합니다 - 초기 렌더링에서는
// 절대 쓰지 않습니다.
function todayLocalDateStr() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function todayLocalHourStr() {
  return String(new Date().getHours()).padStart(2, "0");
}

// lib/trends.js가 이미 계산해 둔 결과(rising/newEntries/trend6h/
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
//
// onShowHistory: isbn13이 있는 행에만 "순위 변화" 버튼을 보여주고, 누르면
// (isbn13, title)로 호출합니다. isbn13이 없는(match_status="no_isbn") 행은
// 과거 이력을 추적할 수 없으므로 버튼 자체를 표시하지 않습니다.
function BookRow({ row, highlightSurge, onShowHistory }) {
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
      {row.isbn13 && onShowHistory && (
        <button
          type="button"
          className="rank-history-button"
          title="순위 변화 보기"
          aria-label="순위 변화 보기"
          onClick={() => onShowHistory(row.isbn13, row.title)}
        >
          📈
        </button>
      )}
      <RankChange rankChange={row.rank_change} matchStatus={row.match_status} />
    </div>
  );
}

// highlightSurge: 실시간 탭에서 BookColumn을 렌더링할 때만 true로 넘겨,
// 20위 이상 급상승 도서를 BookRow에서 강조 표시하게 합니다. 종합/분야별
// 탭은 이 prop을 넘기지 않으므로 기존 표시 방식 그대로 유지됩니다.
//
// collapsible: 모바일 화면에서 서점 헤더를 눌러 그 서점의 목록만 접었다
// 펼 수 있게 합니다(종합/분야별/실시간 탭 공통). 접힘 여부는
// CSS(.column.collapsed .book-list)로만 숨기고 모바일 media query 안에서만
// 적용되므로, 데스크톱에서는 접혀 있는 상태여도 항상 목록이 그대로
// 보입니다(기존 3열 레이아웃 유지).
function BookColumn({
  bookstore,
  rows,
  error,
  query,
  onlyWisdom,
  highlightSurge,
  collapsible,
  onShowHistory,
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
            onShowHistory={onShowHistory}
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

  // 날짜 조회 상태. historyStoreData가 null이 아니면(=historyMode) 서버
  // props(storeData/categoryData/realtimeData) 대신 /api/history로 받아온
  // 스냅샷을 화면에 표시합니다. 종합·분야별은 날짜(historyDate) 하나만
  // 쓰고, 실시간은 날짜(historyRealtimeDate)와 시(historyRealtimeHour,
  // "00"~"23")를 따로 관리합니다 - 실시간 수집이 1시간에 1번만 이뤄지는
  // 데이터 구조와 맞춰 분 단위 선택은 아예 없습니다. 셋 다 초기값은 빈
  // 문자열(서버 렌더링과 동일하게 유지 - hydration mismatch 방지)로
  // 시작해 마운트 후 useEffect에서만 "오늘/지금"으로 채웁니다.
  const [historyDate, setHistoryDate] = useState("");
  const [historyRealtimeDate, setHistoryRealtimeDate] = useState("");
  const [historyRealtimeHour, setHistoryRealtimeHour] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyFetchError, setHistoryFetchError] = useState(null);
  const [historyStoreData, setHistoryStoreData] = useState(null);
  const [historyErrors, setHistoryErrors] = useState({});
  const [historyResolvedAt, setHistoryResolvedAt] = useState({});

  // 분야 탭의 "오늘(최신)" 조회 결과 캐시. 서버(app/page.js)는 더 이상
  // 분야별 데이터를 미리 조회하지 않고, 분야 탭을 처음 클릭한 시점에만
  // /api/history를 호출합니다(lazy load). 한 번 조회한 분야는 다른 탭에
  // 갔다가 다시 눌러도 이 캐시에서 즉시 꺼내 쓰고 재조회하지 않습니다.
  // 과거 날짜 조회는 캐시하지 않고(날짜를 바꾸면 매번 다시 조회) "오늘"
  // 결과만 캐시합니다 - 종합/실시간 탭은 이 캐시를 전혀 쓰지 않고 기존과
  // 동일하게 탭/날짜가 바뀔 때마다 항상 다시 조회합니다.
  const [categoryTodayCache, setCategoryTodayCache] = useState({});

  // 탭을 1단(종합/실시간 베스트셀러)과 2단(분야별 14개)으로 분리해서
  // 렌더링합니다. categories(=lib/categories.js의 CATEGORIES)의 배열
  // 순서가 그대로 2단 탭의 표시 순서가 됩니다.
  const primaryTabs = useMemo(() => [TOTAL_CATEGORY, REALTIME_TAB], []);
  const isTotal = selectedCategory === TOTAL_CATEGORY;
  const isRealtime = selectedCategory === REALTIME_TAB;
  const historyMode = historyStoreData !== null;

  // 현재 탭에서 실제로 쓰이는 날짜(+시) 입력값 하나. 실시간 탭은
  // "YYYY-MM-DDTHH" 형식(분 없음)으로 합쳐서 씁니다. 이 값이 바뀌거나
  // (날짜/시 선택) 탭/분야가 바뀌면 아래 useEffect가 자동으로 다시
  // 조회합니다 - 더 이상 "조회" 버튼을 누를 필요가 없습니다. 아직(마운트
  // 직후 짧은 순간) 비어있으면 오늘 날짜(/지금 시)가 채워지기 전이라는
  // 뜻입니다.
  const currentDateValue = isRealtime
    ? historyRealtimeDate && historyRealtimeHour
      ? `${historyRealtimeDate}T${historyRealtimeHour}`
      : ""
    : historyDate;
  // 선택한 시점이 "지금"이 아니면 과거 시점을 보고 있는 것으로 판단합니다.
  // 종합/분야 탭은 날짜 단위로만 비교하고, 실시간 탭은 시 단위까지 비교합니다
  // (분 선택 UI를 없앤 만큼, 오늘 날짜에서 다른 시를 고르는 것도 명백히
  // "다른 시점을 본다"는 의도이므로 이땐 재조회가 필요합니다 - 날짜만
  // 비교하면 같은 날 안에서 시를 바꿔도 재조회를 건너뛰고 "지금" 데이터를
  // 그대로 보여주는 오류가 생깁니다). currentDateValue가 빈 문자열인
  // 마운트 직전에는 todayLocalDateStr()/todayLocalHourStr()를 아예
  // 호출하지 않으므로(단락 평가) 서버 렌더링 결과와 항상 동일합니다.
  const isPastSelection = isRealtime
    ? currentDateValue !== "" &&
      currentDateValue !== `${todayLocalDateStr()}T${todayLocalHourStr()}`
    : currentDateValue !== "" &&
      currentDateValue.slice(0, 10) !== todayLocalDateStr().slice(0, 10);

  function exitHistoryMode() {
    setHistoryStoreData(null);
    setHistoryErrors({});
    setHistoryResolvedAt({});
    setHistoryFetchError(null);
  }

  function selectTab(tab) {
    setSelectedCategory(tab);
    exitHistoryMode();
  }

  // 마운트 후 클라이언트에서만 오늘 날짜/지금 시로 채웁니다(서버 렌더링
  // 시점에는 절대 실행되지 않으므로 hydration mismatch가 없습니다).
  useEffect(() => {
    setHistoryDate(todayLocalDateStr());
    setHistoryRealtimeDate(todayLocalDateStr());
    setHistoryRealtimeHour(todayLocalHourStr());
  }, []);

  // 날짜 입력값이 바뀌거나(오늘로 되돌리는 경우 포함) 탭/분야가 바뀔
  // 때마다 자동으로 다시 조회합니다. 별도의 "조회" 버튼은 없습니다. 단,
  // (종합 탭 또는 실시간 탭) + "오늘"인 경우는 app/page.js가 서버 렌더링
  // 시점에 이미 최신 데이터(storeData/realtimeData prop)를 내려줬으므로
  // /api/history를 또 호출하지 않고 exitHistoryMode()로 historyStoreData를
  // 비워 서버 props를 그대로 쓰게 합니다(activeStoreData의 기본 분기) -
  // 페이지를 열 때마다 같은 데이터를 서버·클라이언트에서 두 번 조회하던
  // 중복을 없앤 것입니다. 분야 탭(종합/실시간이 아닌 탭)이면서 "오늘"을
  // 보는 중이라면 categoryTodayCache를 확인해서, 이미 조회했거나(직접
  // 클릭) 백그라운드 프리페치로 이미 받아둔 분야는 네트워크 요청 없이
  // 캐시된 값을 그대로 씁니다. 과거 날짜 조회는 기존과 동일하게 항상
  // 다시 조회합니다.
  useEffect(() => {
    if (!currentDateValue) return; // 마운트 직후 아직 오늘 날짜가 안 채워진 순간
    if ((isTotal || isRealtime) && !isPastSelection) {
      exitHistoryMode();
      return;
    }
    if (!isTotal && !isRealtime && !isPastSelection) {
      const cached = categoryTodayCache[selectedCategory];
      if (cached) {
        setHistoryStoreData(cached.storeData);
        setHistoryErrors(cached.errors);
        setHistoryResolvedAt(cached.resolvedAt);
        setHistoryFetchError(null);
        return;
      }
    }
    fetchHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentDateValue, isTotal, isRealtime, selectedCategory, isPastSelection]);

  // 페이지 초기 렌더링(종합 탭 표시)이 끝난 뒤, 화면을 막지 않는 상태로
  // 14개 분야의 "오늘" 데이터를 백그라운드에서 미리 받아 categoryTodayCache를
  // 채워둡니다. 사용자가 실제로 분야 탭을 클릭할 때는 (이미 프리페치가
  // 끝났다면) 네트워크 요청 없이 즉시 표시됩니다. 초기 로딩과 완전히
  // 분리된 별도의 useEffect라 마운트 직후 백그라운드에서 조용히
  // 시작되며, 종합/실시간 탭이 화면에 뜨는 시점을 전혀 지연시키지
  // 않습니다. historyDate가 "오늘"로 채워지는 순간 딱 한 번만 실행되도록
  // ref로 막아뒀습니다 - 이후 사용자가 날짜를 바꾸거나 탭을 오가도 다시
  // 실행되지 않습니다(재실행돼도 결과가 달라지진 않지만, 매번 14개 요청을
  // 다시 보내는 건 낭비이므로). 이미 캐시된 분야(사용자가 먼저 클릭해
  // 조회된 경우)는 건너뛰고, 실패한 분야는 조용히 무시합니다(사용자가
  // 나중에 그 탭을 클릭하면 기존처럼 그 시점에 다시 시도합니다).
  const categoryPrefetchStartedRef = useRef(false);
  useEffect(() => {
    if (!historyDate || categoryPrefetchStartedRef.current || categories.length === 0) {
      return;
    }
    categoryPrefetchStartedRef.current = true;
    let cancelled = false;
    const at = endOfDayISO(historyDate);

    Promise.all(
      categories.map(async (category) => {
        if (categoryTodayCache[category]) return; // 이미 캐시됨(직접 클릭 등)
        try {
          const params = new URLSearchParams({ scope: "category", category, at });
          const res = await fetch(`/api/history?${params.toString()}`);
          const json = await res.json();
          if (cancelled || !res.ok) return;
          setCategoryTodayCache((prev) =>
            prev[category]
              ? prev
              : {
                  ...prev,
                  [category]: {
                    storeData: json.storeData || {},
                    errors: json.errors || {},
                    resolvedAt: json.resolvedAt || {},
                  },
                }
          );
        } catch (e) {
          // 백그라운드 프리페치 실패는 조용히 무시합니다.
        }
      })
    );

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyDate, categories]);

  async function fetchHistory() {
    const params = new URLSearchParams();
    if (isRealtime) {
      if (!historyRealtimeDate || !historyRealtimeHour) return;
      params.set("scope", "realtime");
      params.set("at", endOfHourISO(historyRealtimeDate, historyRealtimeHour));
    } else {
      if (!historyDate) return;
      params.set("scope", isTotal ? "total" : "category");
      if (!isTotal) params.set("category", selectedCategory);
      params.set("at", endOfDayISO(historyDate));
    }

    setHistoryLoading(true);
    setHistoryFetchError(null);
    try {
      const res = await fetch(`/api/history?${params.toString()}`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "조회에 실패했습니다.");
      const nextStoreData = json.storeData || {};
      const nextErrors = json.errors || {};
      const nextResolvedAt = json.resolvedAt || {};
      setHistoryStoreData(nextStoreData);
      setHistoryErrors(nextErrors);
      setHistoryResolvedAt(nextResolvedAt);
      // 분야 탭의 "오늘" 조회 결과만 캐시에 저장합니다(다음에 같은 분야
      // 탭으로 돌아왔을 때 재조회를 건너뛰기 위함). 종합/실시간, 과거 날짜
      // 조회는 캐시하지 않습니다.
      if (!isTotal && !isRealtime && !isPastSelection) {
        setCategoryTodayCache((prev) => ({
          ...prev,
          [selectedCategory]: {
            storeData: nextStoreData,
            errors: nextErrors,
            resolvedAt: nextResolvedAt,
          },
        }));
      }
    } catch (e) {
      setHistoryFetchError(String(e.message || e));
    } finally {
      setHistoryLoading(false);
    }
  }

  // 도서별 순위 변화 차트 상태. 현재 보고 있는 탭(종합/분야별/실시간)과
  // 동일한 스코프로 /api/book-history를 호출합니다 - 예를 들어 "소설"
  // 분야 목록에서 연 책은 "소설" 분야 TOP10 안에서의 순위 이력을 보여주고,
  // 실시간 탭에서 연 책은 실시간 순위 이력을 보여줍니다.
  const [chartBook, setChartBook] = useState(null); // { isbn13, title }
  const [chartData, setChartData] = useState(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState(null);

  async function openRankHistory(isbn13, title) {
    setChartBook({ isbn13, title });
    setChartData(null);
    setChartError(null);
    setChartLoading(true);
    try {
      const params = new URLSearchParams({ isbn13 });
      if (isRealtime) {
        params.set("scope", "realtime");
      } else if (isTotal) {
        params.set("scope", "total");
      } else {
        params.set("scope", "category");
        params.set("category", selectedCategory);
      }
      const res = await fetch(`/api/book-history?${params.toString()}`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || "조회에 실패했습니다.");
      setChartData(json);
    } catch (e) {
      setChartError(String(e.message || e));
    } finally {
      setChartLoading(false);
    }
  }

  function closeRankHistory() {
    setChartBook(null);
    setChartData(null);
    setChartError(null);
  }

  const activeStoreData = historyMode
    ? historyStoreData
    : isRealtime
    ? realtimeData
    : isTotal
    ? storeData
    : categoryData[selectedCategory] || {};
  const activeErrors = historyMode
    ? historyErrors
    : isRealtime
    ? realtimeErrors
    : isTotal
    ? errors
    : categoryErrors[selectedCategory] || {};

  const activeCollectedAt = useMemo(() => {
    if (historyMode) {
      let latest = null;
      for (const bookstore of bookstores) {
        const t = historyResolvedAt[bookstore];
        if (t && (!latest || t > latest)) latest = t;
      }
      return latest;
    }
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
  }, [historyMode, historyResolvedAt, isTotal, collectedAt, activeStoreData, bookstores]);

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
  // 위한 표시 전용 그룹화. rising/newEntries/trend6h/trend24h 자체의
  // 계산(lib/trends.js)은 그대로이고, 이미 계산된 결과를 bookstore로 나누기만
  // 합니다.
  const risingByStore = useMemo(
    () => groupRowsByStore(rising, bookstores),
    [rising, bookstores]
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

  return (
    <div className="page-shell">
      <div className="header">
        <img src="/logo.png" alt="위즈덤하우스" className="brand-logo" />
        <h1>{isRealtime ? "실시간 베스트셀러 현황" : "주간 베스트셀러 현황"}</h1>
        <div className="meta">{isRealtime ? "매시간 갱신" : "매일 오전 6시 갱신"}</div>
        <div className="meta">{formatDateTime(activeCollectedAt)}</div>
        <div className="category-tabs category-tabs-primary">
          {primaryTabs.map((tab) => (
            <button
              key={tab}
              className={`category-tab${selectedCategory === tab ? " active" : ""}`}
              onClick={() => selectTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="category-tabs category-tabs-secondary">
          {categories.map((tab) => (
            <button
              key={tab}
              className={`category-tab${selectedCategory === tab ? " active" : ""}`}
              onClick={() => selectTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="controls">
          <input
            type="text"
            className="search-input"
            placeholder="도서명 / 저자 / 출판사 / ISBN13 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {isRealtime ? (
            <>
              <input
                type="date"
                className="date-input"
                value={historyRealtimeDate}
                onChange={(e) => setHistoryRealtimeDate(e.target.value)}
              />
              <select
                className="hour-select"
                value={historyRealtimeHour}
                onChange={(e) => setHistoryRealtimeHour(e.target.value)}
                aria-label="조회 시각(시)"
              >
                {Array.from({ length: 24 }, (_, hour) => {
                  const hh = String(hour).padStart(2, "0");
                  return (
                    <option key={hh} value={hh}>
                      {hh}시
                    </option>
                  );
                })}
              </select>
            </>
          ) : (
            <input
              type="date"
              className="date-input"
              value={historyDate}
              onChange={(e) => setHistoryDate(e.target.value)}
            />
          )}
          {historyLoading && (
            <span className="history-loading">불러오는 중...</span>
          )}
          <div className="controls-actions">
            {(query || onlyWisdom) && (
              <button
                className="reset-button"
                onClick={() => {
                  setQuery("");
                  setOnlyWisdom(false);
                }}
              >
                초기화
              </button>
            )}
            <button
              className={`wisdom-filter-button${onlyWisdom ? " active" : ""}`}
              onClick={() => setOnlyWisdom((v) => !v)}
            >
              위즈덤하우스만 보기
            </button>
          </div>
        </div>
        {historyFetchError && (
          <div className="history-error">{historyFetchError}</div>
        )}
        {isPastSelection && (
          <div className="history-banner">
            📅 과거 기록 조회 중 — 선택한 시점 이전 가장 최근 스냅샷을
            보여줍니다. 오늘(지금)로 되돌리면 최신 데이터로 돌아옵니다.
          </div>
        )}
      </div>

      {Object.keys(activeErrors).length > 0 && (
        <div className="error-banner">
          {Object.entries(activeErrors)
            .map(([store, msg]) => `${store}: ${msg}`)
            .join("  ·  ")}
        </div>
      )}

      <div className={`columns${historyLoading ? " loading" : ""}`}>
        {bookstores.map((bookstore) => (
          <BookColumn
            key={bookstore}
            bookstore={bookstore}
            rows={activeStoreData[bookstore] || []}
            error={activeErrors[bookstore]}
            query={query}
            onlyWisdom={onlyWisdom}
            highlightSurge={isRealtime}
            collapsible
            onShowHistory={openRankHistory}
          />
        ))}
      </div>

      {isTotal && !isPastSelection && (
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
                      <ul className="trend-list">
                        {risingByStore[bookstore].map((r) => (
                          <li key={`${r.bookstore}-${r.isbn13}-rise`} className="trend-item">
                            <span className="trend-item-title">{r.title}</span>
                            <span className="trend-item-sub">
                              {r.author || "저자 미상"} · {r.publisher || "출판사 미상"} ·{" "}
                              <span className="trend-item-meta-up">
                                ↑{r.rank_change} · {r.rank}위
                              </span>
                            </span>
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
              <ul className="trend-list">
                {simultaneousRise.map((b) => (
                  <li key={b.isbn13} className="trend-item">
                    <span className="trend-item-title">{b.title}</span>
                    <span className="trend-item-sub">
                      {b.author || "저자 미상"} · {b.publisher || "출판사 미상"} ·{" "}
                      <span className="trend-item-meta-up">
                        {b.stores
                          .map((s) => `${s.bookstore} ↑${s.rank_change}`)
                          .join(" · ")}
                      </span>
                    </span>
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

      {!isRealtime && !isPastSelection && (
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

      {isRealtime && !isPastSelection && (
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
                        <li key={`${bookstore}-${r.isbn13 || r.title}-surge`} className="trend-item">
                          <span className="trend-item-title">{r.title}</span>
                          <span className="trend-item-sub">
                            {r.author || "저자 미상"} · {r.publisher || "출판사 미상"} ·{" "}
                            <span className="trend-item-meta-up">
                              현재 {r.rank}위 · ▲{r.rank_change}
                            </span>
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
                  <li key={b.isbn13} className="trend-item">
                    <span className="trend-item-title">{b.title}</span>
                    <span className="trend-item-sub">
                      {b.author || "저자 미상"} · {b.publisher || "출판사 미상"} ·{" "}
                      <span className="trend-item-meta-up">
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
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

        </div>
      </div>
      )}

      {chartBook && (
        <div className="chart-modal-backdrop" onClick={closeRankHistory}>
          <div
            className="chart-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`${chartBook.title} 순위 변화`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="chart-modal-header">
              <h3>{chartBook.title}</h3>
              <button
                type="button"
                className="chart-modal-close"
                onClick={closeRankHistory}
                aria-label="닫기"
              >
                ✕
              </button>
            </div>
            <div className="chart-modal-scope">
              {isRealtime ? "실시간 베스트셀러" : isTotal ? "종합" : selectedCategory}{" "}
              기준 순위 변화
            </div>
            {chartLoading && <p className="trend-empty">불러오는 중...</p>}
            {chartError && <p className="history-error">{chartError}</p>}
            {chartData && (
              <RankHistoryChart series={chartData.series} bookstores={bookstores} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

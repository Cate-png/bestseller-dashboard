"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { isWisdomHouse } from "../lib/wisdomhouse";
import {
  getRisingBooksByStore,
  getNewEntries,
  getSimultaneousRise,
  getCommonBooks,
} from "../lib/trends";
import { getSteadyBooks } from "../lib/steadyBooks";
import { normalizeStoreCategory, DISPLAY_CATEGORIES } from "../lib/categoryMapping";
import {
  getRealtimeSurgingBooks,
  getRealtimeSimultaneousRise,
} from "../lib/realtimeInsights";
import RankHistoryChart from "./RankHistoryChart";
import CategoryDistributionChart from "./CategoryDistributionChart";

const COLUMN_CLASS = {
  교보문고: "kyobo",
  예스24: "yes24",
  알라딘: "aladin",
};

// 순위표 헤더(서점명)를 클릭하면 이동할 서점 원본 베스트셀러 페이지.
// 주간/일간/실시간 탭에 맞는 서점 원본 URL로 각각 연결됩니다(전부 실측
// 확인된 실제 페이지 - 예스24 주간/실시간은 종합 TOP100을 수집하는
// 비공개 API가 아니라 사람이 보는 공개 페이지를 별도로 확인해 채웠고,
// 교보/알라딘은 기존 수집 스크립트(test_save_*.py)가 이미 쓰고 있는
// URL을 그대로 재사용했습니다).
const STORE_LINKS = {
  교보문고: {
    weekly: "https://store.kyobobook.co.kr/bestseller/total/weekly",
    daily: "https://store.kyobobook.co.kr/bestseller/online/daily",
    realtime: "https://store.kyobobook.co.kr/bestseller/realtime",
  },
  예스24: {
    weekly: "https://www.yes24.com/product/category/weekbestseller?categoryNumber=001",
    daily: "https://www.yes24.com/product/category/daybestseller?categoryNumber=001",
    realtime: "https://www.yes24.com/Product/Category/RealTimeBestSeller?categoryNumber=001",
  },
  알라딘: {
    weekly: "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=Bestseller",
    daily: "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=DailyBest",
    realtime: "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=NowBest",
  },
};

// 헤더의 "최종 업데이트" 표시 전용: "YYYY. M. D. HH:MM" (연/월/일 사이는
// ". "로 구분하고 월/일은 0 패딩하지 않음, 시:분만 2자리로 유지, "기준"
// 문구는 붙이지 않음). 주간/실시간 탭 모두 이 형식을 공유합니다.
function formatUpdatedAt(iso) {
  if (!iso) return "데이터 없음";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}. ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

// 날짜(YYYY-MM-DD, <input type="date"> 값)를 "그 날짜의 마지막 순간(UTC
// 23:59:59.999)"의 ISO 문자열로 바꿉니다. 과거 기록 조회에서 "이 날짜 이전
// 가장 최근 스냅샷"을 찾을 때 상한선으로 씁니다(정확한 타임존 보정 없이
// 날짜 단위로만 판단하는 단순한 방식입니다).
function endOfDayISO(dateStr) {
  return new Date(`${dateStr}T23:59:59.999Z`).toISOString();
}

// 날짜 + 시(0~23, "00"~"23")를 "그 시간대의 마지막 순간"의 ISO(UTC) 문자열로
// 바꿉니다. 실시간 수집은 매시 정각에 트리거되지만 실제 저장 시각은 몇 분씩
// 밀릴 수 있어(예: 14시 수집이 14:03에 완료), 상한을 정확히 "HH:00:00"으로
// 두면 그 시간대 스냅샷을 놓치고 한 시간 전으로 밀려날 수 있습니다. 그래서
// 그 시간의 끝(HH:59:59.999)을 상한으로 씁니다.
//
// endOfDayISO처럼 문자열 뒤에 "Z"를 붙여 그대로 UTC로 해석하면 안 됩니다 -
// 날짜 단위에서는 자정 근처 몇 시간 오차가 크게 티가 안 나지만, 시 단위
// 선택에서는 이게 KST(UTC+9)와 UTC의 9시간 차이를 그대로 반영해버려서
// "22시"를 선택해도 실제로는 그 다음 날 07:59(KST)까지의 데이터를 찾는
// 심각한 버그가 됩니다(예스24에서 22:44에 3위였던 책이 22시/23시 조회에
// 안 보이던 원인). new Date(y, m-1, d, h, ...)처럼 로컬(=KST로 가정) 구성
// 요소로 Date를 만들면 브라우저가 알아서 올바르게 UTC로 변환해줍니다.
function endOfHourISO(dateStr, hourStr) {
  const [year, month, day] = dateStr.split("-").map(Number);
  const hour = Number(hourStr);
  return new Date(year, month - 1, day, hour, 59, 59, 999).toISOString();
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

// lib/trends.js가 이미 계산해 둔 결과(newEntries 등)를 bookstore
// 필드로만 나누는 순수 표시용 그룹화입니다. 새로운 집계/계산은 하지 않고,
// 각 서점 목록 안의 항목·순서·값은 그대로 유지합니다.
function groupRowsByStore(rows, bookstores) {
  const byStore = {};
  for (const bookstore of bookstores) {
    byStore[bookstore] = rows.filter((r) => r.bookstore === bookstore);
  }
  return byStore;
}

// "꾸준한 강세" 카드에서 서점별 현재 순위를 표시할 때 씁니다. 그 서점에서
// 지금 TOP20 밖이면(currentRankByStore에 값이 없으면) "권외"로 보여줍니다.
function formatSteadyRank(rank) {
  return typeof rank === "number" ? `${rank}위` : "권외";
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

// "급상승 도서" 카드 전용 행. r.rank(서점의 실제 현재 순위)와
// r.rank_change(직전 수집 대비 등락, lib/trends.js가 이미 계산해 저장해
// 둔 값)를 그대로 매핑해서 보여줄 뿐, 목록 안에서의 배열 순번은 전혀
// 사용하지 않습니다. 등락 표시(▲/▼)는 이 카드만의 표기 형식이라 기존
// RankChange(↑/↓)와는 별도 컴포넌트로 분리했습니다 - 다른 카드의 표시는
// 건드리지 않습니다.
function TrendRiseChange({ rankChange }) {
  if (typeof rankChange === "number" && rankChange > 0) {
    return <span className="trend-row-change up">▲ {rankChange}</span>;
  }
  if (typeof rankChange === "number" && rankChange < 0) {
    return <span className="trend-row-change down">▼ {Math.abs(rankChange)}</span>;
  }
  return <span className="trend-row-change flat">-</span>;
}

// url이 있으면(=서점 원본 데이터에 링크가 있으면) 제목 전체를 그 서점의
// 원본 페이지로 이동하는 링크로 감쌉니다(기존 BookRow의 도서명 링크 처리
// 방식과 동일 - target="_blank"/rel="noopener noreferrer"). url이 없는
// 행은 임의로 링크를 만들지 않고 기존과 동일하게 일반 텍스트로 둡니다.
function TrendBookRow({ rank, title, author, publisher, rankChange, url }) {
  return (
    <li className="trend-row">
      <span className="trend-row-rank">{rank}위</span>
      <span className="trend-row-info">
        {url ? (
          <a
            className="trend-row-title"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {title}
          </a>
        ) : (
          <span className="trend-row-title">{title}</span>
        )}
        <span className="trend-row-sub">
          {author || "저자 미상"} · {publisher || "출판사 미상"}
        </span>
      </span>
      <TrendRiseChange rankChange={rankChange} />
    </li>
  );
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
          추이
        </button>
      )}
      <RankChange rankChange={row.rank_change} matchStatus={row.match_status} />
    </div>
  );
}

// highlightSurge: 실시간·종합 탭에서 BookColumn을 렌더링할 때 true로 넘겨,
// 20위 이상 급상승 도서를 BookRow에서 강조 표시하게 합니다. 분야별 탭은
// 이 prop을 넘기지 않으므로 기존 표시 방식 그대로 유지됩니다.
//
// collapsible: 모바일 화면에서 서점 헤더를 눌러 그 서점의 목록만 접었다
// 펼 수 있게 합니다(종합/분야별/실시간 탭 공통). 접힘 여부는
// CSS(.column.collapsed .book-list)로만 숨기고 모바일 media query 안에서만
// 적용되므로, 데스크톱에서는 접혀 있는 상태여도 항상 목록이 그대로
// 보입니다(기존 3열 레이아웃 유지).
// capRows: 주간/실시간 탭에서 순위 목록을 처음엔 TOP15까지만 보여주고
// 나머지는 내부 스크롤로 보게 합니다(book-list-capped, CSS에서 높이만
// 제한 - 데이터 자체나 rows 배열은 전혀 자르지 않으므로 검색/필터는 기존과
// 동일하게 전체 rows를 대상으로 동작합니다). 일간/분야별 탭은 이 prop을
// 넘기지 않아 기존과 동일하게(데스크톱 80vh, 모바일 펼치면 전체) 동작합니다.
function BookColumn({
  bookstore,
  rows,
  error,
  query,
  onlyWisdom,
  highlightSurge,
  collapsible,
  capRows,
  onShowHistory,
  linkType,
}) {
  const [collapsed, setCollapsed] = useState(false);
  const visibleRows = rows.filter(
    (r) => matchesSearch(r, query) && (!onlyWisdom || isWisdomHouse(r.publisher))
  );

  // linkType(주간/일간/실시간)에 맞는 서점 원본 페이지 URL이 있으면
  // 서점명 자체를 그 페이지로 이동하는 링크로 만듭니다. collapsible
  // 헤더는 기존에 헤더 전체가 <button>(모바일 접기/펼치기)이었는데,
  // <button> 안에 <a>를 중첩하면 유효하지 않은 HTML이라 클릭 동작이
  // 꼬이므로, 서점명(링크)과 접기/펼치기 버튼(종수+화살표)을 분리했습니다
  // - 데스크톱에서는 이 버튼이 시각적으로 아무 효과가 없었고(접기 CSS가
  // 모바일 전용), 모바일에서는 이제 서점명을 누르면 이동, 종수/화살표
  // 부분을 누르면 기존처럼 접고 펼 수 있습니다.
  const storeHref = linkType ? STORE_LINKS[bookstore]?.[linkType] : null;
  const storeNameNode = storeHref ? (
    <a
      href={storeHref}
      target="_blank"
      rel="noopener noreferrer"
      className="column-header-store-link"
    >
      {bookstore}
    </a>
  ) : (
    bookstore
  );

  return (
    <div className={`column${collapsible && collapsed ? " collapsed" : ""}`}>
      {collapsible ? (
        <div className={`column-header column-header-toggle ${COLUMN_CLASS[bookstore] || ""}`}>
          <span>{storeNameNode}</span>
          <button
            type="button"
            className="column-header-collapse-btn"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={`${bookstore} 목록 ${collapsed ? "펼치기" : "접기"}`}
          >
            <span className="column-count">
              ({visibleRows.length}/{rows.length})
            </span>
            <span className="column-toggle-icon" aria-hidden="true">
              ▾
            </span>
          </button>
        </div>
      ) : (
        <div className={`column-header ${COLUMN_CLASS[bookstore] || ""}`}>
          {storeNameNode}{" "}
          <span className="column-count">
            ({visibleRows.length}/{rows.length})
          </span>
        </div>
      )}
      <div className={`book-list${capRows ? " book-list-capped" : ""}`}>
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

// "지금 급상승 도서" 카드. 주간/일간/실시간 탭이 전부 이 컴포넌트 하나를
// 그대로 재사용합니다(디자인을 각 탭마다 따로 구현하지 않음) - 탭마다 다른
// 건 byStore에 넘기는 데이터(risingByStore/dailyRisingByStore/
// realtimeSurgingByStore)뿐이고, 그 계산 로직(lib/trends.js,
// lib/realtimeInsights.js)은 전혀 건드리지 않았습니다. byStore[bookstore]의
// 각 행은 기존과 동일하게 { rank, title, author, publisher, rank_change,
// url, isbn13 } 형태이고, url은 항상 서점 원본 데이터에 있던 값만 씁니다.
function SurgingBooksCard({ byStore, bookstores }) {
  return (
    <TrendCard title="🔥 지금 급상승 도서" className="trend-card-wide">
      {bookstores.every((b) => (byStore[b] || []).length === 0) ? (
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
              {(byStore[bookstore] || []).length === 0 ? (
                <p className="trend-empty">데이터가 부족합니다.</p>
              ) : (
                <ul className="trend-row-list">
                  {byStore[bookstore].map((r) => (
                    <TrendBookRow
                      key={`${bookstore}-${r.isbn13 || r.title}-${r.rank}-surge`}
                      rank={r.rank}
                      title={r.title}
                      author={r.author}
                      publisher={r.publisher}
                      rankChange={r.rank_change}
                      url={r.url}
                    />
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </TrendCard>
  );
}

const TOTAL_CATEGORY = "종합";
const REALTIME_TAB = "실시간 베스트셀러";
// 종합 일간 베스트셀러(rankings.category="일간"). 종합(주간)/실시간과는
// 완전히 별개의 데이터셋으로, 1단(종합) 탭 안에서 주간/일간/실시간 중
// 하나로 선택합니다.
const DAILY_TOTAL_TAB = "종합 일간";

// 1단(종합) 탭의 내부 식별자(=selectedCategory 값)와 화면에 보여줄 짧은
// 라벨을 분리합니다. 2단(분야) 탭은 분야 이름 자체가 곧 라벨이라 별도
// 매핑이 필요 없습니다.
const PRIMARY_TAB_LABELS = {
  [TOTAL_CATEGORY]: "주간",
  [DAILY_TOTAL_TAB]: "일간",
  [REALTIME_TAB]: "실시간",
};

// 현재 선택된 탭(종합/실시간/분야)을 새로고침·뒤로가기/앞으로가기에도
// 유지하기 위해 URL 쿼리(view, category)로부터 복원합니다. 파라미터가
// 없거나 잘못된 값(존재하지 않는 category 등)이면 항상 안전하게
// "종합"으로 떨어집니다 - 기존 링크(쿼리 없음)의 기본 동작과 동일합니다.
// 실시간 탭은 realtime_rankings에 category 개념이 없어(app/page.js,
// Dashboard의 분야 탭 로직 참고) view=realtime일 때는 category 값과
// 무관하게 항상 실시간 탭으로 취급합니다.
function resolveSelectedCategoryFromParams(searchParams, categories) {
  const view = searchParams.get("view");
  if (view === "realtime") return REALTIME_TAB;
  if (view === "daily") return DAILY_TOTAL_TAB;
  if (view === "weekly") {
    const category = searchParams.get("category");
    if (category && categories.includes(category)) return category;
  }
  return TOTAL_CATEGORY;
}

// selectTab에서 쓰는 반대 방향 변환(선택된 탭 -> URL 쿼리스트링). "종합"은
// 쿼리 없이 기본 경로 그대로 둡니다.
function buildTabSearch(tab) {
  const params = new URLSearchParams();
  if (tab === REALTIME_TAB) {
    params.set("view", "realtime");
  } else if (tab === DAILY_TOTAL_TAB) {
    params.set("view", "daily");
  } else if (tab !== TOTAL_CATEGORY) {
    params.set("view", "weekly");
    params.set("category", tab);
  }
  return params.toString();
}

export default function Dashboard({
  bookstores,
  storeData,
  errors,
  collectedAt,
  weeklySavedAt = null,
  dailyStoreData = {},
  dailyErrors = {},
  dailyCollectedAt = null,
  dailySavedAt = null,
  steadyRows = [],
  categories = [],
  categoryData = {},
  categoryErrors = {},
  realtimeData = {},
  realtimeErrors = {},
}) {
  const [query, setQuery] = useState("");
  const [onlyWisdom, setOnlyWisdom] = useState(false);

  // 선택된 탭(종합/실시간/분야)은 컴포넌트 자체 state가 아니라 URL 쿼리
  // (?view=...&category=...)에서 파생시킵니다 - 새로고침해도 URL이 그대로
  // 있으니 선택 상태가 자동으로 유지되고, 뒤로가기/앞으로가기도 브라우저가
  // 원래 하던 대로 동작합니다.
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const selectedCategory = useMemo(
    () => resolveSelectedCategoryFromParams(searchParams, categories),
    [searchParams, categories]
  );

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
  // scope=total일 때만 채워지는 "실제 DB 저장 완료 시각"(서점별). collected_at
  // 기반 historyResolvedAt과 별개로 헤더 표시에만 씁니다.
  const [historyResolvedSavedAt, setHistoryResolvedSavedAt] = useState({});

  // 분야 탭의 "오늘(최신)" 조회 결과 캐시. 서버(app/page.js)는 더 이상
  // 분야별 데이터를 미리 조회하지 않고, 분야 탭을 처음 클릭한 시점에만
  // /api/history를 호출합니다(lazy load). 한 번 조회한 분야는 다른 탭에
  // 갔다가 다시 눌러도 이 캐시에서 즉시 꺼내 쓰고 재조회하지 않습니다.
  // 과거 날짜 조회는 캐시하지 않고(날짜를 바꾸면 매번 다시 조회) "오늘"
  // 결과만 캐시합니다 - 종합/실시간 탭은 이 캐시를 전혀 쓰지 않고 기존과
  // 동일하게 탭/날짜가 바뀔 때마다 항상 다시 조회합니다.
  const [categoryTodayCache, setCategoryTodayCache] = useState({});

  // 실시간 탭에서 사용자가 날짜/시 드롭다운을 "직접" 바꿔서 과거 시점을
  // 보고 있는 중인지 추적합니다. isPastSelection(아래)은 "선택값 !=
  // 지금"만 비교하므로, 탭을 19시에 열어두고 20시가 될 때까지 아무것도
  // 안 한 경우("아직 갱신 안 된 지금")와 사용자가 18시를 일부러 선택한
  // 경우("명시적 과거 조회")를 구분하지 못합니다. 이 ref가 그 구분을
  // 담당합니다: 날짜/시 입력을 사용자가 직접 바꿀 때만 true로 세팅하고,
  // "지금"으로 동기화할 때(마운트, 지금으로 돌아가기, 아래 자동/수동
  // 갱신)는 false로 되돌립니다. true인 동안은 시간대 자동 감지·새로고침
  // 버튼의 "지금으로 점프" 동작 둘 다 이 선택을 절대 건드리지 않습니다.
  const userAdjustedRealtimeRef = useRef(false);

  // 실시간 탭 자동 갱신 감지 기준값. "지금까지 화면에 반영된 것으로 아는
  // 가장 최근 실시간 회차"의 resolvedAt(=collected_at)을 들고 있습니다.
  // null이면 아직 기준값을 세운 적이 없다는 뜻입니다(첫 틱에서만 세팅).
  const lastKnownRealtimeRoundRef = useRef(null);

  // 탭을 1단(종합/실시간 베스트셀러)과 2단(분야별 14개)으로 분리해서
  // 렌더링합니다. categories(=lib/categories.js의 CATEGORIES)의 배열
  // 순서가 그대로 2단 탭의 표시 순서가 됩니다.
  const primaryTabs = useMemo(
    () => [TOTAL_CATEGORY, DAILY_TOTAL_TAB, REALTIME_TAB],
    []
  );
  const isTotal = selectedCategory === TOTAL_CATEGORY;
  const isRealtime = selectedCategory === REALTIME_TAB;
  // 종합 일간 탭. 아직 데이터/조회 로직이 없으므로 이 탭이 선택된 동안은
  // 아래 자동 조회 useEffect에서 완전히 건너뛰고(네트워크 요청 없음),
  // 콘텐츠 영역에는 "준비 중" 안내만 보여줍니다.
  const isDaily = selectedCategory === DAILY_TOTAL_TAB;
  const historyMode = historyStoreData !== null;

  // 헤더 "최종 업데이트" 옆 ⓘ 툴팁 문구. 실시간 탭만 수집 주기가 다르고
  // (매시 00분·30분), 주간/일간/분야별 탭은 전부 collect.yml/
  // collect-daily.yml이 매일 06:00 KST에 도는 동일한 스케줄이라 문구가
  // 같습니다(분야 탭은 별도로 요청받지 않았지만, 같은 06:00 수집이라
  // 주간과 같은 문구를 씁니다). 이 문구는 화면 표시용 안내일 뿐이라
  // 실제 수집 로직/스케줄 자체는 전혀 건드리지 않았습니다.
  const updateInfoText = isRealtime
    ? "각 서점의 베스트셀러 데이터는 특정 시점에 수집한 결과입니다. 서점별 집계·업데이트 시점에 따라 실제 서점 페이지와 차이가 있을 수 있습니다.\n\n수집 시각: 매일 00분·30분"
    : "각 서점의 베스트셀러 데이터는 특정 시점에 수집한 결과입니다. 서점별 집계·업데이트 시점에 따라 실제 서점 페이지와 차이가 있을 수 있습니다.\n\n수집 시각: 매일 오전 6:00";

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
    setHistoryResolvedSavedAt({});
    setHistoryFetchError(null);
  }

  function selectTab(tab) {
    // router.push 대신 history.pushState를 직접 써서, 탭 전환마다
    // 서버 컴포넌트(app/page.js)가 다시 조회되는 걸 피합니다(탭 데이터는
    // 이미 아래 useEffect가 /api/history로 따로 받아오므로 여기서 서버
    // 라운드트립이 하나 더 생길 이유가 없습니다). Next.js는 이 방식의
    // history.pushState도 감지해 useSearchParams()를 갱신해주고, 브라우저
    // 뒤로가기/앞으로가기(popstate)는 원래대로 동작합니다.
    const search = buildTabSearch(tab);
    const url = search ? `${pathname}?${search}` : pathname;
    window.history.pushState(null, "", url);
    exitHistoryMode();
  }

  // "과거 기록 조회 중" 배너의 버튼에서 호출합니다. 현재 탭에서 쓰는 날짜
  // (실시간 탭은 날짜+시)를 오늘/지금으로 되돌리기만 하면, currentDateValue가
  // 바뀌어 자동조회 useEffect가 알아서 실행됩니다 - 종합/실시간은
  // exitHistoryMode로 서버 props를 다시 쓰고, 분야 탭은 categoryTodayCache가
  // 있으면 그대로, 없으면 새로 조회합니다(날짜 input을 직접 오늘로 바꾸는
  // 것과 완전히 동일한 경로).
  function returnToNow() {
    if (isRealtime) {
      userAdjustedRealtimeRef.current = false;
      setHistoryRealtimeDate(todayLocalDateStr());
      setHistoryRealtimeHour(todayLocalHourStr());
      router.refresh();
    } else {
      setHistoryDate(todayLocalDateStr());
    }
  }

  // 실시간 탭을 "지금"으로 맞출 때 공용으로 씁니다(새로고침 버튼, 아래
  // 시간대 자동 감지 둘 다 여기로 옵니다). 날짜/시 상태만 지금으로
  // 맞추면 화면은 여전히 이 페이지가 "맨 처음 열렸을 때"의 서버 props
  // (realtimeData, app/page.js가 내려준 값)를 그대로 쓰게 됩니다 -
  // historyMode가 아닐 때 activeStoreData는 realtimeData를 직접 쓰기
  // 때문입니다. 그래서 router.refresh()로 서버 컴포넌트를 다시 실행시켜
  // realtime_rankings의 실제 최신 스냅샷을 새로 받아옵니다(app/page.js는
  // force-dynamic + revalidate=0이라 캐시 없이 항상 DB를 다시 조회함).
  function syncRealtimeToNow() {
    userAdjustedRealtimeRef.current = false;
    setHistoryRealtimeDate(todayLocalDateStr());
    setHistoryRealtimeHour(todayLocalHourStr());
    router.refresh();
  }

  // 마운트 후 클라이언트에서만 오늘 날짜/지금 시로 채웁니다(서버 렌더링
  // 시점에는 절대 실행되지 않으므로 hydration mismatch가 없습니다).
  useEffect(() => {
    setHistoryDate(todayLocalDateStr());
    setHistoryRealtimeDate(todayLocalDateStr());
    setHistoryRealtimeHour(todayLocalHourStr());
  }, []);

  // 실시간 탭을 열어둔 채로 있는 동안, 실제 새 회차가 저장됐는지를 직접
  // 확인해서 자동으로 화면을 갱신합니다.
  //
  // 예전에는 "시(hour)가 바뀌었는지"만 비교했는데(todayLocalHourStr()),
  // 수집 주기가 1시간 -> 30분으로 바뀌면서 이 비교가 시대에 뒤떨어지게
  // 됐습니다 - 13:01 회차 다음에 13:30 회차가 새로 생겨도 "13시"라는
  // 값 자체는 그대로라 감지를 못 하고, 다음 정시(14:00)가 될 때까지
  // 화면이 최대 수십 분간 정체되는 문제가 있었습니다(실측으로 확인:
  // GitHub Actions는 13:34에 정상 완료·DB에도 13:30 회차가 정상
  // 저장됐지만, 열어둔 탭은 시가 바뀌지 않아 갱신되지 않았음).
  //
  // 이제는 시각 비교 대신, /api/history?scope=realtime으로 "지금" 기준
  // 실제 최신 회차의 resolvedAt(=collected_at)을 직접 조회해서 마지막으로
  // 화면에 반영한 값과 다르면(=새 회차가 생겼으면) 그때만
  // syncRealtimeToNow()를 호출합니다. 30분/1시간 어떤 주기로 바뀌어도
  // 이 비교 자체는 항상 정확합니다(실제 DB 값을 직접 비교하므로). 서점
  // 3곳 중 하나라도 새 회차가 생기면 갱신되도록 최댓값(가장 최근 값)을
  // 기준으로 봅니다. 이 fetch는 순수 조회용이라 상태를 바꾸지 않고,
  // 실제로 변경을 감지했을 때만 syncRealtimeToNow()가 서버를 다시
  // 조회합니다. 첫 틱은 비교 기준값만 세우고 갱신을 트리거하지 않습니다
  // (마운트 직후 불필요한 새로고침 방지). 사용자가 과거 시간대를 직접
  // 선택해 보고 있는 중(userAdjustedRealtimeRef)에는 기존과 동일하게
  // 절대 건드리지 않습니다. 주간/일간/분야별 탭은 이 useEffect가
  // isRealtime일 때만 동작하므로 전혀 영향을 받지 않습니다.
  useEffect(() => {
    if (!isRealtime) return;
    const CHECK_INTERVAL_MS = 30000;
    let cancelled = false;

    const id = setInterval(async () => {
      if (userAdjustedRealtimeRef.current) return;
      try {
        const params = new URLSearchParams({
          scope: "realtime",
          at: new Date().toISOString(),
        });
        const res = await fetch(`/api/history?${params.toString()}`);
        if (!res.ok || cancelled) return;
        const json = await res.json();
        const resolvedAt = json.resolvedAt || {};
        let latestRound = null;
        for (const bookstore of bookstores) {
          const t = resolvedAt[bookstore];
          if (t && (!latestRound || t > latestRound)) latestRound = t;
        }
        if (!latestRound) return;

        if (lastKnownRealtimeRoundRef.current === null) {
          // 이 탭에서 처음 확인하는 것 - 기준값만 세우고 넘어갑니다.
          lastKnownRealtimeRoundRef.current = latestRound;
          return;
        }
        if (latestRound !== lastKnownRealtimeRoundRef.current) {
          lastKnownRealtimeRoundRef.current = latestRound;
          syncRealtimeToNow();
        }
      } catch (e) {
        // 감지 실패는 조용히 무시하고 다음 주기(30초 후)에 다시 시도합니다.
      }
    }, CHECK_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRealtime, bookstores]);

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
    if ((isTotal || isRealtime || isDaily) && !isPastSelection) {
      exitHistoryMode();
      return;
    }
    if (!isTotal && !isRealtime && !isDaily && !isPastSelection) {
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
  }, [currentDateValue, isTotal, isRealtime, isDaily, selectedCategory, isPastSelection]);

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
      params.set("scope", isTotal ? "total" : isDaily ? "daily" : "category");
      if (!isTotal && !isDaily) params.set("category", selectedCategory);
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
      setHistoryResolvedSavedAt(json.resolvedSavedAt || {});
      // 분야 탭의 "오늘" 조회 결과만 캐시에 저장합니다(다음에 같은 분야
      // 탭으로 돌아왔을 때 재조회를 건너뛰기 위함). 종합/실시간, 과거 날짜
      // 조회는 캐시하지 않습니다.
      if (!isTotal && !isRealtime && !isDaily && !isPastSelection) {
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
  // 분야 목록에서 연 책은 "소설" 분야 TOP20 안에서의 순위 이력을 보여주고,
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
      } else if (isDaily) {
        params.set("scope", "daily");
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
    : isDaily
    ? dailyStoreData
    : categoryData[selectedCategory] || {};
  const activeErrors = historyMode
    ? historyErrors
    : isRealtime
    ? realtimeErrors
    : isTotal
    ? errors
    : isDaily
    ? dailyErrors
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
    if (isDaily) return dailyCollectedAt;
    let latest = null;
    for (const bookstore of bookstores) {
      const rows = activeStoreData[bookstore] || [];
      if (rows.length > 0) {
        const t = rows[0].collected_at;
        if (!latest || t > latest) latest = t;
      }
    }
    return latest;
  }, [
    historyMode,
    historyResolvedAt,
    isTotal,
    collectedAt,
    isDaily,
    dailyCollectedAt,
    activeStoreData,
    bookstores,
  ]);

  // 헤더에 "최종 업데이트"로 표시할 시각. 종합(주간)/일간 탭은 3개 서점의
  // rankings 저장이 실제로 모두 끝난 시각(collection_runs.run_at 기반,
  // weeklySavedAt·dailySavedAt / historyResolvedSavedAt)을 우선 쓰고, 아직
  // 그 값이 없으면(과거 데이터 등) 기존 collected_at 기반 activeCollectedAt
  // 으로 대체합니다. 분야별/실시간 탭은 이번 변경 대상이 아니라 기존
  // activeCollectedAt을 그대로 씁니다.
  const activeWeeklySavedAt = useMemo(() => {
    if (!isTotal && !isDaily) return activeCollectedAt;
    if (historyMode) {
      let latest = null;
      for (const bookstore of bookstores) {
        const t = historyResolvedSavedAt[bookstore];
        if (t && (!latest || t > latest)) latest = t;
      }
      return latest || activeCollectedAt;
    }
    return (isDaily ? dailySavedAt : weeklySavedAt) || activeCollectedAt;
  }, [
    isTotal,
    isDaily,
    historyMode,
    historyResolvedSavedAt,
    bookstores,
    weeklySavedAt,
    dailySavedAt,
    activeCollectedAt,
  ]);

  const allRows = useMemo(() => {
    const merged = [];
    for (const bookstore of bookstores) {
      for (const row of storeData[bookstore] || []) {
        merged.push({ ...row, bookstore });
      }
    }
    return merged;
  }, [bookstores, storeData]);

  const newEntries = useMemo(() => getNewEntries(allRows, 10), [allRows]);
  const simultaneousRise = useMemo(
    () => getSimultaneousRise(allRows, 2, 10),
    [allRows]
  );
  const commonBooks = useMemo(() => getCommonBooks(allRows, 2, 10), [allRows]);

  // "꾸준한 강세": 최근 7회 수집 중 TOP20을 5회 이상 유지한 도서. steadyRows는
  // app/page.js가 이미 "최근 7회 x TOP20 이내"로 걸러 내려준 rankings 원본이고,
  // 여기서는 lib/steadyBooks.js로 순수 집계만 합니다.
  const steadyResult = useMemo(
    () => getSteadyBooks(steadyRows, { bookstores, totalRounds: 7, minRounds: 5, minHits: 5, limit: 10 }),
    [steadyRows, bookstores]
  );

  // 종합 탭 하단 트렌드 카드를 실시간 탭과 동일한 서점별 3열 구조로 보여줍니다.
  // risingByStore는 서점별로 완전히 독립적으로 TOP5를 계산합니다(getRisingBooksByStore
  // 참고) - 절대 임계값이나 전체 풀 상위 N개 방식이 아니라서, 한 서점의
  // rank_change가 구조적으로 크게 나와도 다른 서점이 밀려나지 않습니다.
  // newEntriesByStore는 newEntries(lib/trends.js) 계산 결과를 bookstore로
  // 나누기만 하는 표시 전용 그룹화입니다.
  const risingByStore = useMemo(
    () => getRisingBooksByStore(allRows, bookstores, 5),
    [allRows, bookstores]
  );
  const newEntriesByStore = useMemo(
    () => groupRowsByStore(newEntries, bookstores),
    [newEntries, bookstores]
  );

  // 일간 탭 전용 "지금 급상승 도서": dailyStoreData(category="일간")만 쓰고
  // 종합(storeData)/실시간(realtimeData)과는 절대 섞지 않습니다. 계산은
  // 종합 탭과 동일하게 기존 getRisingBooksByStore를 그대로 재사용합니다
  // (새 계산 로직 없음).
  const dailyAllRows = useMemo(() => {
    const merged = [];
    for (const bookstore of bookstores) {
      for (const row of dailyStoreData[bookstore] || []) {
        merged.push({ ...row, bookstore });
      }
    }
    return merged;
  }, [bookstores, dailyStoreData]);

  const dailyRisingByStore = useMemo(
    () => getRisingBooksByStore(dailyAllRows, bookstores, 5),
    [dailyAllRows, bookstores]
  );

  // 분야별 종수: 종합(주간) TOP100 각 도서에 저장된 store_category(서점이
  // 그 도서에 직접 매긴 원본 분야 - 교보 saleCmdtClstName, 알라딘/예스24
  // 상세페이지 breadcrumb)를 그대로 집계합니다. 예전에는 "14개 분야 TOP20
  // 목록에 isbn13이 있는지"로 간접 추정했지만(그래서 14개 분야 밖 장르와
  // TOP20 밖을 구분 못 했고, 한 책이 여러 분야에 걸쳐 합계가 100을 넘기도
  // 했습니다), 이제 도서 하나당 store_category 값 하나로 정확히 매겨지므로
  // counts 합계 + uncategorized는 항상 total과 같습니다. store_category가
  // 아예 없는(원본을 못 가져온) 도서만 uncategorized로 셉니다 - 14개 분야
  // 밖의 실제 서점 분야(예: "어린이")는 그 이름 그대로 counts의 키가 되고
  // "미분류"로 뭉뚱그리지 않습니다. normalizeStoreCategory(lib/categoryMapping.js)로
  // 서점별 표기 차이(예: 교보 "경제/경영" -> "경제·경영")만 명백한 동의어인
  // 경우에만 하나의 표시 분야로 정규화하고, 여러 분야에 걸쳐 애매한 원본
  // 분류(예: "소설/시/희곡", "건강 취미")는 정규화하지 않고 원본 이름
  // 그대로 독립된 표시 분야로 둡니다(3사를 무조건 같은 분야로 통합하지
  // 않음). store_category 원본 값 자체나 DB는 전혀 바꾸지 않고 이 집계
  // 시점에만 적용합니다.
  // categoryTodayCache(14개 분야 탭
  // 프리페치)는 더 이상 이 계산에 쓰지 않습니다 - storeData만 있으면
  // 바로 계산되므로 14개 분야가 다 로딩될 때까지 기다릴 필요가 없어졌고,
  // 분야 탭 자체(별도 기능)는 categoryTodayCache를 여전히 그대로 씁니다.
  const categoryDistribution = useMemo(() => {
    const result = {};
    for (const bookstore of bookstores) {
      const totalBooks = storeData[bookstore] || [];
      const counts = {};
      let uncategorized = 0;
      for (const book of totalBooks) {
        const raw = (book.store_category || "").trim();
        if (!raw) {
          uncategorized += 1;
          continue;
        }
        const normalized = normalizeStoreCategory(bookstore, raw);
        counts[normalized] = (counts[normalized] || 0) + 1;
      }
      result[bookstore] = { counts, uncategorized, total: totalBooks.length };
    }
    return result;
  }, [bookstores, storeData]);

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
        <button
          type="button"
          className="brand-logo-button"
          onClick={() => selectTab(TOTAL_CATEGORY)}
          aria-label="종합 베스트셀러 홈으로 이동"
        >
          <img src="/logo.png" alt="위즈덤하우스" className="brand-logo" />
        </button>
        <h1>
          {isRealtime
            ? "실시간 베스트셀러"
            : isDaily
            ? "일간 베스트셀러"
            : "주간 베스트셀러"}
        </h1>
        <div className="meta">
          최종 업데이트 {formatUpdatedAt(isRealtime ? activeCollectedAt : activeWeeklySavedAt)}
          <span className="info-icon-wrap">
            <button
              type="button"
              className="info-icon"
              aria-label="수집 시각 안내"
              aria-describedby="update-info-tooltip"
            >
              i
            </button>
            <span
              id="update-info-tooltip"
              className="info-icon-tooltip info-icon-tooltip-align-right"
              role="tooltip"
            >
              {updateInfoText}
            </span>
          </span>
          {isRealtime && (
            <button
              type="button"
              className={`refresh-button${historyLoading ? " is-loading" : ""}`}
              onClick={() => {
                // 실시간 탭 + 사용자가 과거 시간대를 직접 선택한 게 아니라면
                // ("지금"을 보고 있는 중이라면) 새로고침은 현재 KST 시간대로
                // 먼저 맞춘 뒤 조회합니다 - 그래야 19시에 열어둔 탭에서 20시가
                // 된 뒤 눌러도 20시 데이터가 나옵니다. 과거 시간대를 직접
                // 보고 있는 중이면 그 선택을 그대로 두고 같은 시점만 다시
                // 조회합니다(강제로 지금으로 이동시키지 않음).
                if (isRealtime && !userAdjustedRealtimeRef.current) {
                  syncRealtimeToNow();
                } else {
                  fetchHistory();
                }
              }}
              disabled={historyLoading}
              aria-label="현재 화면 데이터 새로고침"
              title="현재 화면 데이터 새로고침"
            >
              ↻
            </button>
          )}
        </div>
        {/* 1단: "종합"은 클릭 불가능한 고정 라벨이고, 그 옆 버튼들(주간/일간/
            실시간)이 종합 베스트셀러의 기간·유형 선택지입니다. */}
        <div className="tab-row tab-row-primary">
          <span className="tab-row-label">종합</span>
          <div className="category-tabs category-tabs-primary">
            {primaryTabs.map((tab) => (
              <button
                key={tab}
                className={`category-tab${selectedCategory === tab ? " active" : ""}`}
                onClick={() => selectTab(tab)}
              >
                {PRIMARY_TAB_LABELS[tab]}
              </button>
            ))}
          </div>
        </div>
        {/* 2단: "분야"도 고정 라벨이고, 그 옆의 작은 "주간" 텍스트는 클릭할
            수 없는 보조 설명입니다(분야별 베스트셀러는 주간 데이터만
            제공된다는 의미) - 1단의 [주간] 버튼과는 별개입니다. */}
        <div className="tab-row tab-row-secondary">
          <span className="tab-row-label">분야</span>
          <span className="tab-row-sublabel">주간</span>
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
                onChange={(e) => {
                  userAdjustedRealtimeRef.current = true;
                  setHistoryRealtimeDate(e.target.value);
                }}
              />
              <select
                className="hour-select"
                value={historyRealtimeHour}
                onChange={(e) => {
                  userAdjustedRealtimeRef.current = true;
                  setHistoryRealtimeHour(e.target.value);
                }}
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
            <span>
              📅 과거 기록 조회 중 — 선택한 시점 이전 가장 최근 스냅샷을
              보여줍니다.
            </span>
            <button
              type="button"
              className="history-banner-button"
              onClick={returnToNow}
            >
              지금으로 돌아가기
            </button>
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
            highlightSurge={isRealtime || isTotal || isDaily}
            collapsible
            capRows={isTotal || isRealtime}
            onShowHistory={openRankHistory}
            linkType={isRealtime ? "realtime" : isDaily ? "daily" : isTotal ? "weekly" : undefined}
          />
        ))}
      </div>

      {isTotal && !isPastSelection && (
      <div className="trend-section">
        <div className="trend-grid">
          <SurgingBooksCard byStore={risingByStore} bookstores={bookstores} />

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

          <TrendCard title="서점별 분야 분포 (종합 TOP100 기준)" className="trend-card-wide">
            <CategoryDistributionChart
              distribution={categoryDistribution}
              trackedCategories={DISPLAY_CATEGORIES}
              bookstores={bookstores}
            />
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

          <TrendCard title="꾸준한 강세" className="trend-card-wide">
            <p className="trend-card-desc">
              최근 수집 기준 상위권을 꾸준히 유지한 도서입니다.
            </p>
            {steadyResult.insufficientData || steadyResult.books.length === 0 ? (
              <p className="trend-empty">아직 충분한 비교 데이터가 없습니다.</p>
            ) : (
              <ul className="trend-list">
                {steadyResult.books.map((b) => (
                  <li key={b.isbn13} className="trend-item">
                    <span className="trend-item-title">{b.title}</span>
                    <span className="trend-item-sub">{b.author || "저자 미상"}</span>
                    <span className="trend-item-sub">
                      교보 {formatSteadyRank(b.currentRankByStore["교보문고"])} · 예스24{" "}
                      {formatSteadyRank(b.currentRankByStore["예스24"])} · 알라딘{" "}
                      {formatSteadyRank(b.currentRankByStore["알라딘"])}
                    </span>
                    <span className="trend-item-sub trend-item-meta-up">
                      {steadyResult.roundsAvailable}회 중 {b.hitCount}회 TOP20 · 평균{" "}
                      {b.avgRank.toFixed(1)}위
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </TrendCard>
        </div>
      </div>
      )}

      {isDaily && !isPastSelection && (
      <div className="trend-section">
        <div className="trend-grid">
          <SurgingBooksCard byStore={dailyRisingByStore} bookstores={bookstores} />
        </div>
      </div>
      )}

      {isRealtime && !isPastSelection && (
      <div className="realtime-insight-section">
        <div className="realtime-insight-stack">
          <SurgingBooksCard byStore={realtimeSurgingByStore} bookstores={bookstores} />

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

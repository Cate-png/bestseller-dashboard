"use client";

import { useMemo, useState } from "react";

const COLUMN_CLASS = {
  교보문고: "kyobo",
  예스24: "yes24",
  알라딘: "aladin",
};

// 대시보드 표시 분야 35개(lib/categoryMapping.js DISPLAY_CATEGORIES) 전용
// 색상을 "표시 분야명 -> 색상"으로 완전히 고정합니다. count 순위나
// 서점별 정렬 순서로 색을 배정하지 않으므로, 어느 서점에서 보든 같은
// 표시 분야는 항상 같은 색이고("소설"과 "소설/시/희곡"은 서로 다른
// 표시 분야라 다른 색), 데이터가 바뀌어도(다음 주 수집, 다른 서점) 색이
// 바뀌지 않습니다. 35색 전체가 dataviz 팔레트 검증기(scripts/
// validate_palette.js) 기준 lightness band/chroma floor/CVD 분리/일반
// 시야 분리/명도대비를 통과했습니다(명도대비 일부는 WARN이지만, 이
// 컴포넌트는 범례·툴팁·표에 항상 텍스트 라벨이 함께 나오는 구조라
// dataviz 가이드가 요구하는 보조 인코딩 조건을 충족합니다). 예전에는
// 상위 6개만 슬라이스로 보여주고 나머지를 "기타"로 묶었는데(자기계발·
// 에세이처럼 실제로는 뚜렷한 분야인데도 6위 밖이면 뭉뚱그려 보이는
// 문제로 사용자 요청에 따라 제거, 2026-08-26) - 이제 그 서점에 실제로
// 존재하는 분야 수만큼 전부 슬라이스로 쪼개서 보여줍니다.
const CATEGORY_COLORS = {
  // 통합 그룹(14) - 3사 표기 차이를 하나로 묶은 표시 분야
  "경제·경영": "#d65c88",
  인문: "#a30038",
  과학: "#dc5d61",
  역사: "#a50000",
  "사회·정치": "#f64200",
  "기술·IT": "#b50000",
  자기계발: "#e85b00",
  "예술·대중문화": "#a30000",
  어린이: "#ce7500",
  유아: "#863d00",
  청소년: "#c09000",
  "외국어·사전": "#6a6a00",
  "수험서·자격증": "#729f00",
  종교: "#4d6300",
  // 독립 그룹(21) - 서점 고유/복합 원본 분류를 그대로 살린 표시 분야
  소설: "#43a447",
  "소설/시/희곡": "#006e0c",
  만화: "#00b366",
  "만화/라이트노벨": "#007849",
  "시/에세이": "#00b39f",
  에세이: "#007397",
  건강: "#00adcf",
  "취미/실용/스포츠": "#0067af",
  "건강/취미": "#00a0f5",
  "건강 취미": "#0052d0",
  "가정/육아": "#008fff",
  "가정 살림": "#0048bd",
  요리: "#6185ed",
  "요리/살림": "#4137bc",
  "종교/역학": "#8979e6",
  여행: "#6425af",
  "중/고등참고서": "#a86dd5",
  초등참고서: "#7e1296",
  한국소개도서: "#c064bb",
  잡지: "#910075",
  "대학교재/전문서적": "#d15d9a",
};
// 35개 표시 분야에 없는(아직 파악되지 않은) 원본 분류에만 쓰는 색.
const OTHER_COLOR = "#9a9893";

const SIZE = 160;
const CENTER = SIZE / 2;
const R_OUTER = 72;
const R_INNER = 42;
const SLICE_GAP_DEG = 1;

function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

// 인접 조각과는 테두리선으로 분리하지 않고, 시작/끝 각도를 살짝 안쪽으로
// 당겨 얇은 여백(surface gap)만 둡니다.
function donutSlicePath(cx, cy, rOuter, rInner, startAngle, endAngle) {
  const s = startAngle + SLICE_GAP_DEG;
  const e = endAngle - SLICE_GAP_DEG;
  if (e <= s) return null;
  const largeArc = e - s > 180 ? 1 : 0;
  const p1 = polarToCartesian(cx, cy, rOuter, s);
  const p2 = polarToCartesian(cx, cy, rOuter, e);
  const p3 = polarToCartesian(cx, cy, rInner, e);
  const p4 = polarToCartesian(cx, cy, rInner, s);
  return [
    `M ${p1.x} ${p1.y}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${p2.x} ${p2.y}`,
    `L ${p3.x} ${p3.y}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${p4.x} ${p4.y}`,
    "Z",
  ].join(" ");
}

function StoreDonut({ bookstore, slices, total, hovered, onHoverSlice }) {
  let angle = 0;
  const arcs = slices.map((slice) => {
    const start = angle;
    const sweep = total > 0 ? (slice.count / total) * 360 : 0;
    angle += sweep;
    return { ...slice, start, end: angle };
  });

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="category-donut-svg"
      role="img"
      aria-label={`${bookstore} 분야별 종수 비중 도넛 차트`}
    >
      {arcs.map((arc) => {
        const d = donutSlicePath(CENTER, CENTER, R_OUTER, R_INNER, arc.start, arc.end);
        if (!d) return null;
        const isHovered =
          hovered && hovered.bookstore === bookstore && hovered.key === arc.key;
        return (
          <path
            key={arc.key}
            d={d}
            fill={arc.color}
            className={`category-donut-slice${isHovered ? " is-hovered" : ""}`}
            tabIndex={0}
            role="img"
            aria-label={`${arc.label} ${arc.count}종`}
            onMouseEnter={() => onHoverSlice({ bookstore, ...arc })}
            onFocus={() => onHoverSlice({ bookstore, ...arc })}
            onMouseLeave={() => onHoverSlice(null)}
            onBlur={() => onHoverSlice(null)}
          />
        );
      })}
      <text x={CENTER} y={CENTER - 3} textAnchor="middle" className="category-donut-total-value">
        {total}
      </text>
      <text x={CENTER} y={CENTER + 15} textAnchor="middle" className="category-donut-total-label">
        건
      </text>
    </svg>
  );
}

// distribution: Dashboard.jsx의 categoryDistribution({bookstore: {counts,
// uncategorized, total}})을 그대로 받습니다. counts의 키는 store_category를
// normalizeStoreCategory()로 정규화한 "표시 분야명"입니다 - 3사 표기
// 차이만 있는 명백한 동의어는 하나로 묶이고("경제/경영"·"경제 경영"·
// "경제경영" -> "경제·경영"), 서로 다른 분야가 섞인 서점 고유/복합
// 분류(예: "소설/시/희곡", "건강 취미")는 원본 이름 그대로 별도의
// 독립된 표시 분야가 됩니다(3사를 무조건 같은 분야로 묶지 않음).
// trackedCategories(lib/categoryMapping.js DISPLAY_CATEGORIES, 35개
// 표시 분야 전체)는 이 35개 모두를 색상 슬롯 경쟁 대상으로 삼는 데
// 쓰이고, "그 외"(범례의 * 표시)는 이 35개에 없는 - 즉 아직 파악되지
// 않은 새로운 원본 분류에만 붙습니다.
export default function CategoryDistributionChart({
  distribution,
  trackedCategories,
  bookstores,
}) {
  const [hovered, setHovered] = useState(null);
  const [showTable, setShowTable] = useState(false);

  const trackedSet = useMemo(() => new Set(trackedCategories || []), [trackedCategories]);

  // 관측된 모든 분야명에 색을 배정합니다. 35개 표시 분야는
  // CATEGORY_COLORS의 고정 색을 그대로 쓰고, 거기 없는(아직 파악되지
  // 않은) 원본 분류만 OTHER_COLOR를 씁니다 - 상위 N개로 자르지 않고
  // 실제 존재하는 분야 수만큼 전부 색이 배정됩니다.
  const colorByCategory = useMemo(() => {
    const map = {};
    for (const bookstore of bookstores) {
      const counts = distribution[bookstore]?.counts || {};
      for (const name of Object.keys(counts)) {
        if (map[name]) continue;
        map[name] = CATEGORY_COLORS[name] || OTHER_COLOR;
      }
    }
    return map;
  }, [bookstores, distribution]);

  const chartsByStore = useMemo(() => {
    const result = {};
    for (const bookstore of bookstores) {
      const dist = distribution[bookstore] || { counts: {}, uncategorized: 0, total: 0 };
      const slices = [];
      for (const [name, count] of Object.entries(dist.counts)) {
        if (count <= 0) continue;
        slices.push({
          key: name,
          label: name,
          count,
          color: colorByCategory[name] || OTHER_COLOR,
          isOther: !trackedSet.has(name),
        });
      }
      slices.sort((a, b) => b.count - a.count);

      const denominator = slices.reduce((sum, s) => sum + s.count, 0);
      result[bookstore] = {
        slices,
        denominator,
        uncategorized: dist.uncategorized || 0,
        total: dist.total || 0,
      };
    }
    return result;
  }, [bookstores, distribution, colorByCategory, trackedSet]);

  // "표로 보기"용 전체 분야명 목록(모든 서점 합쳐서, 종수 많은 순). 실제
  // 관측된 표시 분야 전부라 서점마다 몇 개가 나올지는 다를 수 있습니다.
  const allCategoryNames = useMemo(() => {
    const totals = new Map();
    for (const bookstore of bookstores) {
      const counts = distribution[bookstore]?.counts || {};
      for (const [name, count] of Object.entries(counts)) {
        totals.set(name, (totals.get(name) || 0) + count);
      }
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
  }, [bookstores, distribution]);

  return (
    <div className="category-donut-wrap">
      <div className="category-donut-grid">
        {bookstores.map((bookstore) => {
          const chart = chartsByStore[bookstore] || {
            slices: [],
            denominator: 0,
            uncategorized: 0,
          };
          return (
            <div className="category-donut-column" key={bookstore}>
              <div className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}>
                {bookstore}
              </div>
              {chart.denominator === 0 && chart.uncategorized === 0 ? (
                <p className="trend-empty">데이터가 부족합니다.</p>
              ) : (
                <>
                  {chart.denominator > 0 && (
                    <StoreDonut
                      bookstore={bookstore}
                      slices={chart.slices}
                      total={chart.denominator}
                      hovered={hovered}
                      onHoverSlice={setHovered}
                    />
                  )}
                  <ul className="category-donut-legend">
                    {chart.slices.map((slice) => (
                      <li
                        key={slice.key}
                        className={`category-donut-legend-item${
                          hovered &&
                          hovered.bookstore === bookstore &&
                          hovered.key === slice.key
                            ? " is-hovered"
                            : ""
                        }`}
                        onMouseEnter={() => setHovered({ bookstore, ...slice })}
                        onMouseLeave={() => setHovered(null)}
                      >
                        <span
                          className="category-donut-swatch"
                          style={{ background: slice.color }}
                          aria-hidden="true"
                        />
                        <span className="category-donut-legend-label">
                          {slice.label}
                          {slice.isOther && "*"}
                        </span>
                        <span className="category-donut-legend-count">{slice.count}종</span>
                      </li>
                    ))}
                  </ul>
                  {chart.uncategorized > 0 && (
                    <p className="category-donut-uncategorized-note">
                      이 외 미분류(원본 분야 정보 없음) {chart.uncategorized}종
                    </p>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      <p className="category-donut-footnote">* 아직 파악되지 않은 새로운 원본 분류</p>

      {hovered && (
        <div className="category-donut-tooltip" aria-live="polite">
          <strong>
            {hovered.bookstore} · {hovered.label}
            {hovered.isOther && "*"}: {hovered.count}종
          </strong>
        </div>
      )}

      <button
        type="button"
        className="rank-chart-table-toggle"
        onClick={() => setShowTable((v) => !v)}
      >
        {showTable ? "표 숨기기" : "표로 보기 (전체 분야)"}
      </button>

      {showTable && (
        <div className="category-count-table-wrap">
          <table className="category-count-table">
            <thead>
              <tr>
                <th>분야</th>
                {bookstores.map((bookstore) => (
                  <th key={bookstore} className={COLUMN_CLASS[bookstore] || ""}>
                    {bookstore}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allCategoryNames.map((name) => (
                <tr key={name}>
                  <td className="category-count-name">
                    {name}
                    {!trackedSet.has(name) && "*"}
                  </td>
                  {bookstores.map((bookstore) => (
                    <td key={bookstore}>{distribution[bookstore]?.counts[name] ?? 0}</td>
                  ))}
                </tr>
              ))}
              <tr className="category-count-uncategorized">
                <td className="category-count-name">미분류</td>
                {bookstores.map((bookstore) => (
                  <td key={bookstore}>{distribution[bookstore]?.uncategorized ?? 0}</td>
                ))}
              </tr>
              <tr className="category-count-total">
                <td className="category-count-name">종합 TOP100</td>
                {bookstores.map((bookstore) => (
                  <td key={bookstore}>{distribution[bookstore]?.total ?? 0}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

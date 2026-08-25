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
// dataviz 가이드가 요구하는 보조 인코딩 조건을 충족합니다). 한 번에
// 화면에 보이는 슬라이스는 MAX_SLICES(6)개로 여전히 제한하지만(인접
// 슬라이스가 6개를 넘으면 구분이 흐려짐 - dataviz 가이드), "어떤 6개가
// 보일지"만 종수로 정하고 "그 6개가 무슨 색일지"는 이 표에서 고정으로
// 가져옵니다.
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
const OTHER_COLOR = "#9a9893";
const MAX_SLICES = 6;

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

  // 35개 표시 분야 전체(통합 그룹 + 독립 그룹)를 색상 슬롯 경쟁에 넣고,
  // 3개 서점 합산 종수로 상위 6개를 정해 그 분야가 화면에 슬라이스로
  // 보일지만 결정합니다(도넛이 6개를 넘으면 구분이 흐려짐 - dataviz
  // 가이드). 상위 6개에 못 든 분야는 도넛에서만 "기타"로 묶이고(시각적
  // 그룹핑일 뿐 - 실제 집계 데이터는 그대로 보존되어 기타에 마우스를
  // 올리면 실제 분야명+건수가 나오고, "표로 보기"에는 35개가 각자 행으로
  // 다 나옵니다). 어떤 색을 쓸지는 순위가 아니라 CATEGORY_COLORS(표시
  // 분야명 -> 고정 색상)에서 그대로 가져오므로, 데이터가 바뀌어도 같은
  // 표시 분야는 항상 같은 색입니다.
  const colorByCategory = useMemo(() => {
    const totals = new Map();
    for (const bookstore of bookstores) {
      const counts = distribution[bookstore]?.counts || {};
      for (const [name, count] of Object.entries(counts)) {
        if (!trackedSet.has(name)) continue;
        totals.set(name, (totals.get(name) || 0) + count);
      }
    }
    const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]);
    const map = {};
    ranked.slice(0, MAX_SLICES).forEach(([name]) => {
      map[name] = CATEGORY_COLORS[name];
    });
    return map;
  }, [bookstores, distribution, trackedSet]);

  const chartsByStore = useMemo(() => {
    const result = {};
    for (const bookstore of bookstores) {
      const dist = distribution[bookstore] || { counts: {}, uncategorized: 0, total: 0 };
      const featured = [];
      const otherBreakdown = [];
      for (const [name, count] of Object.entries(dist.counts)) {
        if (count <= 0) continue;
        if (colorByCategory[name]) {
          featured.push({
            key: name,
            label: name,
            count,
            color: colorByCategory[name],
            isOther: !trackedSet.has(name),
          });
        } else {
          otherBreakdown.push({ label: name, count, isOther: !trackedSet.has(name) });
        }
      }
      featured.sort((a, b) => b.count - a.count);
      otherBreakdown.sort((a, b) => b.count - a.count);
      const otherTotal = otherBreakdown.reduce((sum, o) => sum + o.count, 0);

      const slices = [...featured];
      if (otherTotal > 0) {
        slices.push({
          key: "__other__",
          label: "기타",
          count: otherTotal,
          color: OTHER_COLOR,
          breakdown: otherBreakdown,
        });
      }
      slices.sort((a, b) => b.count - a.count);

      const denominator = featured.reduce((sum, s) => sum + s.count, 0) + otherTotal;
      result[bookstore] = {
        slices,
        denominator,
        uncategorized: dist.uncategorized || 0,
        total: dist.total || 0,
      };
    }
    return result;
  }, [bookstores, distribution, colorByCategory, trackedSet]);

  // "표로 보기"용 전체 분야명 목록(모든 서점 합쳐서, 종수 많은 순). 도넛에서
  // "기타"로 묶인 분야도 여기서는 전부 개별 행으로 나옵니다 - 실제 관측된
  // 표시 분야 전부라 서점마다 몇 개가 나올지는 다를 수 있습니다.
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
      <div className="category-donut-info-row">
        <span className="info-icon-wrap" tabIndex={0}>
          <span className="info-icon" aria-hidden="true">
            i
          </span>
          <span className="info-icon-tooltip" role="tooltip">
            서점별 종합 TOP100 각 도서에 그 서점이 직접 매긴 분야(원본
            분류)를 그대로 집계한 비중입니다 - 도서 한 권은 분야 하나로만
            잡히므로 가운데 숫자는 그 서점의 TOP100 도서 수와 같습니다.
            3사 표기 차이만 있는 명백한 동의어(예: "경제/경영"·"경제
            경영"·"경제경영")만 하나의 분야로 묶었고, 서로 다른 분야가
            섞인 서점 고유 분류(예: "소설/시/희곡", "건강 취미")는 억지로
            합치지 않고 원본 표기 그대로 별도 분야로 남겼습니다. 이름에
            *가 붙은 분야는 아직 파악되지 않은 새로운 원본 분류입니다.
            도넛에서는 비중이 작은 분야를 "기타"로 묶어 보여주지만(마우스를
            올리면 실제 분야명·종수가 그대로 나옵니다), 집계 자체에서
            사라지는 건 아니라 "표로 보기"에는 전 분야가 각자 행으로
            나옵니다. "미분류"는 원본 분야 정보 자체를 가져오지 못한
            도서로, 화면의 "기타"와는 다른 별개 개념입니다.
          </span>
        </span>
      </div>

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

      <div className="category-donut-tooltip" aria-live="polite">
        {hovered ? (
          <>
            <strong>
              {hovered.bookstore} · {hovered.label}
              {hovered.isOther && "*"}: {hovered.count}종
            </strong>
            {hovered.breakdown && hovered.breakdown.length > 0 && (
              <span className="category-donut-tooltip-sub">
                {hovered.breakdown
                  .map((b) => `${b.label}${b.isOther ? "*" : ""} ${b.count}종`)
                  .join(" · ")}
              </span>
            )}
          </>
        ) : (
          <span className="category-donut-tooltip-placeholder">
            슬라이스나 범례에 마우스를 올리면 분야별 종수가 여기에 표시됩니다.
          </span>
        )}
      </div>

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

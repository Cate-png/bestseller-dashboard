"use client";

import { useMemo, useState } from "react";

const COLUMN_CLASS = {
  교보문고: "kyobo",
  예스24: "yes24",
  알라딘: "aladin",
};

// 우리 14개 분야(lib/categories.js CATEGORIES, dataviz 팔레트 검증기로
// 검증된 고정 팔레트) 전용 색상을 "분야명 -> 색상"으로 완전히 고정합니다.
// count 순위나 서점별 정렬 순서로 색을 배정하지 않으므로, 어느 서점에서
// 보든 같은 분야는 항상 같은 색이고, 데이터가 바뀌어도(다음 주 수집,
// 다른 서점) 색이 바뀌지 않습니다. 한 번에 화면에 보이는 슬라이스는
// MAX_SLICES(6)개로 여전히 제한하지만(인접 슬라이스가 6개를 넘으면
// 구분이 흐려짐 - dataviz 가이드), "어떤 6개가 보일지"만 종수로 정하고
// "그 6개가 무슨 색일지"는 이 표에서 고정으로 가져옵니다.
const CATEGORY_COLORS = {
  인문: "#2a78d6",
  경제경영: "#eb6834",
  자기계발: "#1baf7a",
  소설: "#eda100",
  "에세이/시": "#e87ba4",
  사회과학: "#008300",
  역사: "#7a4fd1",
  예술: "#c94c4c",
  과학: "#1e93a8",
  만화: "#8a8f00",
  여행: "#d1789a",
  건강: "#2f8f5b",
  "기술/IT": "#9a5fd6",
  종교: "#b06a2a",
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
// uncategorized, total}})을 그대로 받습니다. counts의 키는 더 이상 고정된
// 14개 분야가 아니라, 각 서점이 실제로 도서에 매긴 원본 분야명(store_category)
// 그대로입니다 - 우리 14개 분야와 이름이 같으면 그 이름 그대로, 다르면
// (예: "어린이", "수험서/자격증") 그 이름 그대로 별도 항목이 됩니다.
// trackedCategories(우리 14개 분야 목록)는 계산에는 안 쓰고, "그 외 분야"
// 표시(범례의 * 표시)에만 씁니다.
export default function CategoryDistributionChart({
  distribution,
  trackedCategories,
  bookstores,
}) {
  const [hovered, setHovered] = useState(null);
  const [showTable, setShowTable] = useState(false);

  const trackedSet = useMemo(() => new Set(trackedCategories || []), [trackedCategories]);

  // 우리 14개 분야만 색상 슬롯 경쟁에 넣고(서점 자체 분야는 색을 배정하지
  // 않고 항상 기타로 묶임), 3개 서점 합산 종수로 상위 6개를 정해 그
  // 분야가 화면에 슬라이스로 보일지만 결정합니다. 어떤 색을 쓸지는 순위가
  // 아니라 CATEGORY_COLORS(분야명 -> 고정 색상)에서 그대로 가져오므로,
  // 데이터가 바뀌어도 같은 분야는 항상 같은 색입니다.
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

  // "표로 보기"용 전체 분야명 목록(모든 서점 합쳐서, 종수 많은 순). 고정
  // 14개가 아니라 실제 관측된 전부라 서점마다 다를 수 있습니다.
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
            이름에 *가 붙은 분야는 우리가 따로 추적하는 14개 분야 목록에는
            없는, 그 서점 자체 분류입니다. 비중이 작은 분야는 "기타"로
            묶었고, "미분류"는 원본 분야 정보 자체를 가져오지 못한 도서입니다
            (그 외에는 미분류로 표시하지 않습니다). 슬라이스나 아래
            범례에 마우스를 올리거나 "표로 보기"에서 분야별 정확한 종수를
            그대로 확인할 수 있습니다.
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

      <p className="category-donut-footnote">* 기존 14개 추적 분야 외 서점 자체 분류</p>

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

"use client";

import { useMemo, useState } from "react";

const COLUMN_CLASS = {
  교보문고: "kyobo",
  예스24: "yes24",
  알라딘: "aladin",
};

// 카테고리 슬라이스 색상: 인접 슬라이스가 6개를 넘으면 구분이 흐려지므로
// (dataviz 가이드 - "past ~7 color classes blur"), 종수가 큰 상위 6개
// 분야에만 고정 팔레트 색을 주고 나머지는 전부 "기타"(회색) 하나로
// 묶습니다. 어떤 6개가 색을 받을지는 3개 서점 합산 종수로 한 번만
// 정해서(useMemo) 서점이 달라져도 같은 분야는 항상 같은 색을 씁니다.
const SLICE_COLORS = [
  "#2a78d6", // blue
  "#eb6834", // orange
  "#1baf7a", // aqua
  "#eda100", // yellow
  "#e87ba4", // magenta
  "#008300", // green
];
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
// uncategorized, total}})을 그대로 받습니다 - 새로 계산하지 않고 그 결과만
// 원그래프용으로 다시 배치합니다. 기존 표(category-count-table)는 그대로
// "표로 보기" 토글 안에 남겨둬서, 슬라이스로 묶인 소수 분야를 포함한 전체
// 실제 데이터를 언제든 확인할 수 있습니다.
export default function CategoryDistributionChart({
  distribution,
  categories,
  bookstores,
  loadedCount,
  totalCategories,
}) {
  const [hovered, setHovered] = useState(null);
  const [showTable, setShowTable] = useState(false);

  const colorByCategory = useMemo(() => {
    const combined = categories.map((category) => ({
      category,
      total: bookstores.reduce(
        (sum, b) => sum + (distribution[b]?.counts[category] ?? 0),
        0
      ),
    }));
    combined.sort((a, b) => b.total - a.total);
    const map = {};
    combined.slice(0, MAX_SLICES).forEach((c, i) => {
      map[c.category] = SLICE_COLORS[i];
    });
    return map;
  }, [categories, bookstores, distribution]);

  const chartsByStore = useMemo(() => {
    const result = {};
    for (const bookstore of bookstores) {
      const dist = distribution[bookstore] || { counts: {}, uncategorized: 0, total: 0 };
      const featured = [];
      const otherBreakdown = [];
      for (const category of categories) {
        const count = dist.counts[category] ?? 0;
        if (count <= 0) continue;
        if (colorByCategory[category]) {
          featured.push({
            key: category,
            label: category,
            count,
            color: colorByCategory[category],
          });
        } else {
          otherBreakdown.push({ label: category, count });
        }
      }
      if (dist.uncategorized > 0) {
        otherBreakdown.push({ label: "미분류", count: dist.uncategorized });
      }
      otherBreakdown.sort((a, b) => b.count - a.count);
      const otherTotal = otherBreakdown.reduce((sum, o) => sum + o.count, 0);

      // 슬라이스(도넛 조각 + 범례 목록)는 항상 그 서점 안에서 종수가 많은
      // 순서대로 나열합니다 - "기타"도 예외 없이 자기 종수 기준으로 같이
      // 정렬합니다(항상 맨 끝에 고정하지 않음).
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
      result[bookstore] = { slices, denominator };
    }
    return result;
  }, [bookstores, categories, distribution, colorByCategory]);

  return (
    <div className="category-donut-wrap">
      <div className="category-donut-info-row">
        <span className="info-icon-wrap" tabIndex={0}>
          <span className="info-icon" aria-hidden="true">
            i
          </span>
          <span className="info-icon-tooltip" role="tooltip">
            서점별 종합 TOP100 도서가 그 서점의 14개 분야 TOP20에 몇 권씩
            들어있는지 비중으로 보여줍니다. 한 도서가 여러 분야에 동시에
            들어있으면 두 분야 모두에 포함되므로, 가운데 숫자(=모든 조각의
            합)는 100건이 아니라 "분야 매칭 총 건수"이고 서점마다 겹치는
            정도가 달라 100을 넘기는 정도도 서로 다릅니다(도서 수 자체가
            다른 게 아닙니다). 비중이 작은 분야는 "기타"로 묶었고, 슬라이스나
            아래 범례에 마우스를 올리거나 "표로 보기"에서 분야별 정확한
            종수를 그대로 확인할 수 있습니다.
          </span>
        </span>
        {loadedCount < totalCategories && (
          <span className="category-donut-loading-note">
            분야 데이터 로딩 중 {loadedCount}/{totalCategories}
          </span>
        )}
      </div>

      <div className="category-donut-grid">
        {bookstores.map((bookstore) => {
          const chart = chartsByStore[bookstore] || { slices: [], denominator: 0 };
          return (
            <div className="category-donut-column" key={bookstore}>
              <div className={`realtime-store-column-header ${COLUMN_CLASS[bookstore] || ""}`}>
                {bookstore}
              </div>
              {chart.denominator === 0 ? (
                <p className="trend-empty">데이터가 부족합니다.</p>
              ) : (
                <>
                  <StoreDonut
                    bookstore={bookstore}
                    slices={chart.slices}
                    total={chart.denominator}
                    hovered={hovered}
                    onHoverSlice={setHovered}
                  />
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
                        <span className="category-donut-legend-label">{slice.label}</span>
                        <span className="category-donut-legend-count">{slice.count}종</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="category-donut-tooltip" aria-live="polite">
        {hovered ? (
          <>
            <strong>
              {hovered.bookstore} · {hovered.label}: {hovered.count}종
            </strong>
            {hovered.breakdown && hovered.breakdown.length > 0 && (
              <span className="category-donut-tooltip-sub">
                {hovered.breakdown.map((b) => `${b.label} ${b.count}종`).join(" · ")}
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
              {categories.map((category) => (
                <tr key={category}>
                  <td className="category-count-name">{category}</td>
                  {bookstores.map((bookstore) => (
                    <td key={bookstore}>
                      {distribution[bookstore]?.counts[category] ?? 0}
                    </td>
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

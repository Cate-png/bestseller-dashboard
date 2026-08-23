"use client";

import { useMemo, useState } from "react";

// 서점 색상은 앱 전체(컬럼 헤더, 배지 등)에서 이미 쓰고 있는 것과 동일한
// 값을 그대로 재사용합니다 - "색상은 개체(서점)를 따른다"는 원칙에 따라
// 서점별 색상을 화면 전체에서 하나로 고정합니다.
const STORE_COLOR = {
  교보문고: "#2d4a3e",
  예스24: "#1e3a8a",
  알라딘: "#d9534f",
};

const WIDTH = 640;
const HEIGHT = 320;
const PAD = { top: 16, right: 16, bottom: 36, left: 40 };
const PLOT_W = WIDTH - PAD.left - PAD.right;
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;

function formatTick(iso, spanMs) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  // 데이터 구간이 이틀 미만(대체로 실시간 스코프)이면 시:분까지, 그 이상이면
  // 날짜까지만 보여줍니다.
  if (spanMs < 1000 * 60 * 60 * 48) {
    return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(
      d.getMinutes()
    )}`;
  }
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
}

export default function RankHistoryChart({ series, bookstores }) {
  const [hover, setHover] = useState(null); // { x, y, bookstore, rank, collectedAt }
  const [showTable, setShowTable] = useState(false);

  const allPoints = useMemo(() => {
    const points = [];
    for (const bookstore of bookstores) {
      for (const p of series[bookstore] || []) {
        points.push({ ...p, bookstore, t: new Date(p.collectedAt).getTime() });
      }
    }
    return points;
  }, [series, bookstores]);

  if (allPoints.length === 0) {
    return (
      <p className="trend-empty">
        저장된 과거 순위 기록이 없습니다. (이 스코프의 순위권에 든 적이
        없거나, 아직 데이터가 쌓이지 않았습니다)
      </p>
    );
  }

  const minT = Math.min(...allPoints.map((p) => p.t));
  const maxT = Math.max(...allPoints.map((p) => p.t));
  const tSpan = maxT - minT || 1;

  const minRank = 1;
  const maxRank = Math.max(10, ...allPoints.map((p) => p.rank));

  const xScale = (t) => PAD.left + ((t - minT) / tSpan) * PLOT_W;
  // rank가 작을수록(1위) 위쪽(작은 y)에 오도록 - SVG는 y가 아래로 갈수록
  // 커지므로 별도 반전 계산 없이 그대로 매핑하면 1위가 자연히 위쪽입니다.
  const yScale = (rank) =>
    PAD.top + ((rank - minRank) / (maxRank - minRank || 1)) * PLOT_H;

  const yTicks = useMemo(() => {
    const ticks = new Set([1, maxRank]);
    const step = Math.max(1, Math.round(maxRank / 4));
    for (let r = step; r < maxRank; r += step) ticks.add(r);
    return [...ticks].sort((a, b) => a - b);
  }, [maxRank]);

  const xTicks = [minT, minT + tSpan / 2, maxT];

  const allDates = useMemo(() => {
    const set = new Set(allPoints.map((p) => p.collectedAt));
    return [...set].sort();
  }, [allPoints]);

  return (
    <div className="rank-chart">
      <div className="rank-chart-legend">
        {bookstores.map((bookstore) => {
          const pts = series[bookstore] || [];
          const latest = pts[pts.length - 1];
          return (
            <div className="rank-chart-legend-item" key={bookstore}>
              <span
                className="rank-chart-swatch"
                style={{ background: STORE_COLOR[bookstore] }}
                aria-hidden="true"
              />
              <span>
                {bookstore}
                {latest ? ` · 최근 ${latest.rank}위` : " · 기록 없음"}
              </span>
            </div>
          );
        })}
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="rank-chart-svg"
        role="img"
        aria-label="서점별 순위 변화 차트 (위쪽일수록 높은 순위)"
      >
        {/* 격자선 + y축 순위 라벨 */}
        {yTicks.map((r) => (
          <g key={`y-${r}`}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yScale(r)}
              y2={yScale(r)}
              className="rank-chart-grid"
            />
            <text x={PAD.left - 8} y={yScale(r)} className="rank-chart-axis-label" textAnchor="end" dominantBaseline="middle">
              {r}위
            </text>
          </g>
        ))}

        {/* x축 시간 라벨 */}
        {xTicks.map((t, i) => (
          <text
            key={`x-${i}`}
            x={xScale(t)}
            y={HEIGHT - PAD.bottom + 18}
            className="rank-chart-axis-label"
            textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}
          >
            {formatTick(new Date(t).toISOString(), tSpan)}
          </text>
        ))}

        {/* 서점별 라인 + 점 */}
        {bookstores.map((bookstore) => {
          const pts = (series[bookstore] || [])
            .map((p) => ({ ...p, t: new Date(p.collectedAt).getTime() }))
            .sort((a, b) => a.t - b.t);
          if (pts.length === 0) return null;

          const pathD = pts
            .map((p, i) => `${i === 0 ? "M" : "L"}${xScale(p.t)},${yScale(p.rank)}`)
            .join(" ");
          const color = STORE_COLOR[bookstore];

          return (
            <g key={bookstore}>
              {pts.length > 1 && (
                <path d={pathD} className="rank-chart-line" style={{ stroke: color }} />
              )}
              {pts.map((p, i) => (
                <circle
                  key={i}
                  cx={xScale(p.t)}
                  cy={yScale(p.rank)}
                  r={4}
                  style={{ fill: color }}
                  className="rank-chart-point"
                  onMouseEnter={() =>
                    setHover({
                      x: xScale(p.t),
                      y: yScale(p.rank),
                      bookstore,
                      rank: p.rank,
                      collectedAt: p.collectedAt,
                    })
                  }
                  onMouseLeave={() => setHover(null)}
                  onClick={() =>
                    setHover((h) =>
                      h && h.bookstore === bookstore && h.collectedAt === p.collectedAt
                        ? null
                        : {
                            x: xScale(p.t),
                            y: yScale(p.rank),
                            bookstore,
                            rank: p.rank,
                            collectedAt: p.collectedAt,
                          }
                    )
                  }
                />
              ))}
            </g>
          );
        })}

        {hover && (
          <g pointerEvents="none">
            <line
              x1={hover.x}
              x2={hover.x}
              y1={PAD.top}
              y2={HEIGHT - PAD.bottom}
              className="rank-chart-crosshair"
            />
          </g>
        )}
      </svg>

      {hover && (
        <div className="rank-chart-tooltip">
          <strong>{hover.bookstore}</strong> · {formatTick(hover.collectedAt, 0)} ·{" "}
          {hover.rank}위
        </div>
      )}

      <button
        type="button"
        className="rank-chart-table-toggle"
        onClick={() => setShowTable((v) => !v)}
      >
        {showTable ? "표 숨기기" : "표로 보기"}
      </button>

      {showTable && (
        <div className="rank-chart-table-wrap">
          <table className="rank-chart-table">
            <thead>
              <tr>
                <th>시각</th>
                {bookstores.map((b) => (
                  <th key={b}>{b}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allDates.map((date) => (
                <tr key={date}>
                  <td>{formatTick(date, 0)}</td>
                  {bookstores.map((b) => {
                    const found = (series[b] || []).find(
                      (p) => p.collectedAt === date
                    );
                    return <td key={b}>{found ? `${found.rank}위` : "-"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

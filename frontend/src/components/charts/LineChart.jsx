import { useMemo, useRef, useState } from 'react';

const WIDTH = 640;
const HEIGHT = 220;
const MARGIN = { top: 12, right: 16, bottom: 28, left: 48 };
const Y_TICKS = 4;
const X_TICKS = 5;

function identity(v) {
  return v;
}

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

/** A reusable SVG line chart: `series` is [{name, color, points: [{x, y}]}].
 * Renders a crosshair+tooltip on hover, a legend for 2+ series (per the
 * dataviz skill: a single series needs no legend, the title already names
 * it), and a same-data table for accessibility. */
export default function LineChart({ title, series, xLabel, yLabel, xFormat = identity, yFormat = identity }) {
  const [hoverX, setHoverX] = useState(null);
  const svgRef = useRef(null);

  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  const allPoints = series.flatMap((s) => s.points);
  const allXs = useMemo(() => [...new Set(allPoints.map((p) => p.x))].sort((a, b) => a - b), [allPoints]);

  const hasData = allPoints.length > 0;
  const xMin = hasData ? Math.min(...allXs) : 0;
  const xMax = hasData ? Math.max(...allXs) : 1;
  const yMaxRaw = hasData ? Math.max(...allPoints.map((p) => p.y)) : 1;
  const yMax = niceMax(yMaxRaw || 1);
  const yMin = 0;

  function xToPx(x) {
    if (xMax === xMin) return MARGIN.left + plotWidth / 2;
    return MARGIN.left + ((x - xMin) / (xMax - xMin)) * plotWidth;
  }
  function yToPx(y) {
    if (yMax === yMin) return MARGIN.top + plotHeight;
    return MARGIN.top + plotHeight - ((y - yMin) / (yMax - yMin)) * plotHeight;
  }

  function pathFor(points) {
    return points
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xToPx(p.x).toFixed(2)} ${yToPx(p.y).toFixed(2)}`)
      .join(' ');
  }

  function handleMove(event) {
    if (!hasData || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const dataX = xMin + ((px - MARGIN.left) / plotWidth) * (xMax - xMin);
    let nearest = allXs[0];
    let best = Infinity;
    for (const x of allXs) {
      const d = Math.abs(x - dataX);
      if (d < best) {
        best = d;
        nearest = x;
      }
    }
    setHoverX(nearest);
  }

  const yTickValues = Array.from({ length: Y_TICKS + 1 }, (_, i) => yMin + ((yMax - yMin) * i) / Y_TICKS);
  const xTickValues = hasData
    ? Array.from({ length: X_TICKS + 1 }, (_, i) => xMin + ((xMax - xMin) * i) / X_TICKS)
    : [];

  const hoverEntries = hoverX == null
    ? []
    : series.map((s) => ({
        name: s.name,
        color: s.color,
        point: s.points.find((p) => p.x === hoverX),
      }));

  const hoverPx = hoverX == null ? null : xToPx(hoverX);
  const showLegend = series.length > 1;

  return (
    <div className="chart-container">
      <h4 className="chart-title">{title}</h4>
      {!hasData ? (
        <p className="group-hint">No data.</p>
      ) : (
        <>
          <svg
            ref={svgRef}
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="chart-svg"
            onMouseMove={handleMove}
            onMouseLeave={() => setHoverX(null)}
          >
            {yTickValues.map((v) => (
              <g key={v}>
                <line
                  x1={MARGIN.left}
                  x2={WIDTH - MARGIN.right}
                  y1={yToPx(v)}
                  y2={yToPx(v)}
                  className="chart-gridline"
                />
                <text x={MARGIN.left - 8} y={yToPx(v)} className="chart-axis-label" textAnchor="end" dy="0.32em">
                  {yFormat(v)}
                </text>
              </g>
            ))}

            {xTickValues.map((v) => (
              <text
                key={v}
                x={xToPx(v)}
                y={HEIGHT - MARGIN.bottom + 16}
                className="chart-axis-label"
                textAnchor="middle"
              >
                {xFormat(v)}
              </text>
            ))}

            {series.map((s) => (
              <path key={s.name} d={pathFor(s.points)} className="chart-line" stroke={s.color} fill="none" />
            ))}

            {series.map((s) => {
              const last = s.points[s.points.length - 1];
              if (!last) return null;
              return (
                <g key={s.name}>
                  <circle cx={xToPx(last.x)} cy={yToPx(last.y)} r={6} fill="var(--panel)" />
                  <circle cx={xToPx(last.x)} cy={yToPx(last.y)} r={4} fill={s.color} />
                </g>
              );
            })}

            {hoverPx != null && (
              <>
                <line
                  x1={hoverPx}
                  x2={hoverPx}
                  y1={MARGIN.top}
                  y2={HEIGHT - MARGIN.bottom}
                  className="chart-crosshair"
                />
                {hoverEntries.map(
                  (e) =>
                    e.point && (
                      <g key={e.name}>
                        <circle cx={xToPx(e.point.x)} cy={yToPx(e.point.y)} r={5} fill="var(--panel)" />
                        <circle cx={xToPx(e.point.x)} cy={yToPx(e.point.y)} r={3} fill={e.color} />
                      </g>
                    )
                )}
              </>
            )}

            {xLabel && (
              <text x={WIDTH / 2} y={HEIGHT - 4} className="chart-axis-title" textAnchor="middle">
                {xLabel}
              </text>
            )}
            {yLabel && (
              <text
                x={-HEIGHT / 2}
                y={14}
                className="chart-axis-title"
                textAnchor="middle"
                transform="rotate(-90)"
              >
                {yLabel}
              </text>
            )}
          </svg>

          {hoverX != null && (
            <div className="chart-tooltip">
              <div className="chart-tooltip-x">{xFormat(hoverX)}</div>
              {hoverEntries.map((e) => (
                <div className="chart-tooltip-row" key={e.name}>
                  <span className="chart-tooltip-key" style={{ background: e.color }} />
                  <span className="chart-tooltip-name">{e.name}</span>
                  <strong className="chart-tooltip-value">
                    {e.point ? yFormat(e.point.y) : '—'}
                  </strong>
                </div>
              ))}
            </div>
          )}

          {showLegend && (
            <div className="chart-legend">
              {series.map((s) => (
                <span className="chart-legend-item" key={s.name}>
                  <span className="chart-legend-key" style={{ background: s.color }} />
                  {s.name}
                </span>
              ))}
            </div>
          )}

          <details className="chart-table-toggle">
            <summary>Table view</summary>
            <table className="results-table">
              <thead>
                <tr>
                  <th>{xLabel || 'x'}</th>
                  {series.map((s) => (
                    <th key={s.name}>{s.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {allXs.map((x) => (
                  <tr key={x}>
                    <td>{xFormat(x)}</td>
                    {series.map((s) => {
                      const point = s.points.find((p) => p.x === x);
                      return <td key={s.name}>{point ? yFormat(point.y) : '—'}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}

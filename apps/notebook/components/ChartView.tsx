// Renders a chart from its source-backed CSV rows. Every mark carries data-row-id / data-value
// attributes so tests can compare what is drawn with the stored inputs.
import type { Chart, ChartRow } from "@/lib/research";
import { formatNumber } from "@/lib/research";


const W = 640;
const H = 300;
const M = { top: 20, right: 16, bottom: 56, left: 56 };
const SERIES_COLORS = ["var(--series-1)", "var(--series-2)"];

function niceTicks(min: number, max: number, count = 5) {
  const span = max - min || 1;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) ?? mag * 10;
  const ticks: number[] = [];
  const last = Math.ceil(max / step) * step;
  for (let t = Math.floor(min / step) * step; t <= last + step / 1e6; t += step) ticks.push(Number(t.toFixed(10)));
  return ticks;
}

function Axis({ ticks, y, label }: { ticks: number[]; y: (v: number) => number; label: string }) {
  return (
    <g aria-hidden="true">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke="var(--grid)" />
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className="tick">
            {formatNumber(t)}
          </text>
        </g>
      ))}
      <text transform={`translate(14 ${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" className="axis-label">
        {label.length > 46 ? label.slice(0, 44) + "…" : label}
      </text>
    </g>
  );
}

function groups(rows: ChartRow[]) {
  const out: { group: string; label: string; rows: ChartRow[] }[] = [];
  for (const r of rows) {
    const g = out.find((x) => x.group === r.group);
    if (g) g.rows.push(r);
    else out.push({ group: r.group, label: r.label, rows: [r] });
  }
  return out;
}

export function ChartView({ chart }: { chart: Chart }) {
  const rows = chart.rows;
  const lo = Math.min(...rows.map((r) => r.lower ?? r.value ?? 0));
  const hi = Math.max(...rows.map((r) => r.upper ?? r.value ?? 0));
  const ref = chart.reference_line ?? null;
  const top = ref ? Math.max(hi, ref.value) : hi;
  const baseline = chart.chart_type === "paired_bars" ? 0 : ref ? Math.min(lo, ref.value) : lo;
  const pad = (top - baseline) * 0.12;
  const ticks = niceTicks(chart.chart_type === "paired_bars" ? 0 : baseline - pad, top + pad);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const y = (v: number) => M.top + (1 - (v - yMin) / (yMax - yMin)) * (H - M.top - M.bottom);
  const gs = groups(rows);
  const band = (W - M.left - M.right) / gs.length;
  const seriesNames = [...new Set(rows.map((r) => r.series))];

  return (
    <figure className="chart" data-chart-id={chart.id}>
      <div className="chart-scroll">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${chart.id}-title`}>
        <title id={`${chart.id}-title`}>{chart.title}</title>
        <Axis ticks={ticks} y={y} label={chart.y_label} />
        {ref && (
          <g data-reference={ref.value}>
            <line x1={M.left} x2={W - M.right} y1={y(ref.value)} y2={y(ref.value)} stroke="var(--ink)" strokeDasharray="4 3" />
            <text x={M.left + 6} y={y(ref.value) - 6} textAnchor="start" className="tick ref-label">
              {ref.label}
            </text>
          </g>
        )}
        {gs.map((g, gi) => {
          const cx = M.left + band * gi + band / 2;
          return (
            <g key={g.group}>
              {g.rows.map((r, ri) => {
                const si = seriesNames.indexOf(r.series);
                const n = g.rows.length;
                const slot = Math.min(band * 0.7, 120) / n;
                const x = cx - (slot * n) / 2 + slot * ri + slot / 2;
                const color = SERIES_COLORS[si % SERIES_COLORS.length];
                const common = {
                  "data-row-id": r.row_id,
                  "data-claim-id": r.claim_id,
                  "data-value": r.value ?? "",
                  "data-lower": r.lower ?? "",
                  "data-upper": r.upper ?? "",
                  className: "mark",
                };
                if (chart.chart_type === "range_bars") {
                  const w = Math.min(36, slot * 0.6);
                  return (
                    <g key={r.row_id}>
                      <rect {...common} x={x - w / 2} width={w} y={y(r.upper!)} height={y(r.lower!) - y(r.upper!)} fill={color} rx={3}>
                        <title>{`${r.label}: ${r.lower}–${r.upper} ${r.unit}`}</title>
                      </rect>
                      <text x={x} y={y(r.upper!) - 5} textAnchor="middle" className="value">{r.upperText}</text>
                      <text x={x} y={y(r.lower!) + 13} textAnchor="middle" className="value">{r.lowerText}</text>
                    </g>
                  );
                }
                if (chart.chart_type === "paired_bars") {
                  const w = slot * 0.8;
                  return (
                    <g key={r.row_id}>
                      <rect {...common} x={x - w / 2} width={w} y={y(r.value!)} height={y(0) - y(r.value!)} fill={color} rx={2}>
                        <title>{`${r.group}, ${r.series}: ${r.value}`}</title>
                      </rect>
                      <text x={x} y={y(r.value!) - 5} textAnchor="middle" className="value">{r.valueText}</text>
                    </g>
                  );
                }
                return (
                  <g key={r.row_id}>
                    <line x1={x} x2={x} y1={y(r.lower!)} y2={y(r.upper!)} stroke={color} strokeWidth={2} />
                    <circle {...common} cx={x} cy={y(r.value!)} r={5} fill={color}>
                      <title>{`${r.label}: ${r.value} (${r.lower}–${r.upper})`}</title>
                    </circle>
                    <text x={x + 9} y={y(r.value!) + 4} className="value">{r.valueText}</text>
                  </g>
                );
              })}
              <text x={cx} y={H - M.bottom + 18} textAnchor="middle" className="tick">
                {chart.chart_type === "range_bars" ? g.label : g.group}
              </text>
            </g>
          );
        })}
        <text x={(M.left + W - M.right) / 2} y={H - 10} textAnchor="middle" className="axis-label">
          {chart.x_label}
        </text>
      </svg>
      </div>
      <p className="scroll-hint">Scroll the chart sideways to see all groups.</p>
      {seriesNames.length > 1 && (
        <div className="legend">
          {seriesNames.map((s, i) => (
            <span key={s}>
              <i style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
              {s}
            </span>
          ))}
        </div>
      )}
      <figcaption>
        <strong>{/[.?!]$/.test(chart.title) ? chart.title : `${chart.title}.`}</strong> {chart.caption}
        <span className="reading-note">How to read it: {chart.reading_note}</span>
      </figcaption>
      <details className="chart-data">
        <summary>Chart inputs and source locations ({rows.length} rows)</summary>
        <div className="table-wrap">
          <table data-testid={`chart-data-${chart.id}`}>
            <thead>
              <tr>
                <th>Row</th>
                <th>Group</th>
                <th>Series</th>
                <th>Value</th>
                <th>Interval</th>
                <th>Unit</th>
                <th>Provenance</th>
                <th>Source location</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.row_id} data-row-id={r.row_id}>
                  <td>{r.row_id}</td>
                  <td>{r.group}</td>
                  <td>{r.series}</td>
                  <td className="num">{r.valueText}</td>
                  <td className="num">{r.lowerText !== "" ? `${r.lowerText} to ${r.upperText}` : ""}</td>
                  <td>{r.unit}</td>
                  <td>{r.provenance === "derived" ? "our calculation" : "reported"}</td>
                  <td>
                    {r.source_section}: {r.source_element}{" "}
                    <a href={`#claim-${r.claim_id}`}>quote</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

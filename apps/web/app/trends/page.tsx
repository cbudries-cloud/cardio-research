"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type Series, type SeriesResponse, type TestEntry } from "@/lib/api";
import { humanize } from "@/lib/format";
import { ErrorNote, Loading, StatusChip, useLoad } from "@/components/ui";

export default function TrendsPage() {
  const tests = useLoad(() => api<TestEntry[]>("/series"));
  const [selected, setSelected] = useState<string | null>(null);
  const [includeUnverified, setIncludeUnverified] = useState(false);
  const key = selected ?? tests.data?.find((t) => t.accepted > 0)?.key ?? tests.data?.[0]?.key ?? null;
  const series = useLoad(
    () => (key ? api<SeriesResponse>(`/series/${encodeURIComponent(key)}?include_unverified=${includeUnverified}`) : Promise.resolve(null)),
    [key, includeUnverified],
  );

  return (
    <div className="stack">
      <div>
        <h1>Trends</h1>
        <p className="subtle">
          Accepted observations over time. Results are split into separate series whenever comparability has not been
          established (collection method, unit, calculated vs measured). Nothing is converted or adjusted.
        </p>
      </div>
      <ErrorNote error={tests.error} />
      {!tests.data ? (
        <Loading />
      ) : tests.data.length === 0 ? (
        <p className="subtle">No observations yet.</p>
      ) : (
        <div className="trends">
          <div className="card test-list" style={{ padding: 0 }}>
            {tests.data.map((t) => (
              <button key={t.key} className={t.key === key ? "active" : ""} onClick={() => setSelected(t.key)}>
                {t.recognized ? humanize(t.label) : `${t.label} (unrecognized)`}
                <span className="subtle">
                  {" "}
                  · {t.accepted} accepted{t.unverified ? `, ${t.unverified} unverified` : ""}
                </span>
              </button>
            ))}
          </div>
          <div className="stack">
            <label className="row" style={{ color: "inherit", fontSize: 14 }}>
              <input type="checkbox" checked={includeUnverified} onChange={(e) => setIncludeUnverified(e.target.checked)} />
              Include unverified candidates (shown hollow)
            </label>
            <ErrorNote error={series.error} />
            {series.data && (
              <>
                {series.data.notices.map((n) => (
                  <div key={n} className="notice warn">
                    {n}
                  </div>
                ))}
                {series.data.series.length === 0 && <p className="subtle">No accepted observations with a usable date for this test.</p>}
                {series.data.series.map((s) => (
                  <SeriesCard key={s.label} s={s} />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SeriesCard({ s }: { s: Series }) {
  return (
    <div className="card stack" data-testid="series" data-method={s.collection_method}>
      <h2 style={{ margin: 0 }}>{s.label}</h2>
      {s.notices.map((n) => (
        <div key={n} className="notice">
          {n}
        </div>
      ))}
      <Chart s={s} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Collected</th>
              <th>Value</th>
              <th>Reference range (that report)</th>
              <th>Lab flag</th>
              <th>Laboratory</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {s.points.map((p) => (
              <tr key={p.observation_id}>
                <td>
                  <Link href={`/observations/${p.observation_id}`}>{p.collection_date}</Link>
                </td>
                <td>
                  {p.comparator ?? ""}
                  {p.value} {s.unit}
                </td>
                <td>{p.reference_range_raw ?? "none reported"}</td>
                <td>{p.lab_flag_raw ?? ""}</td>
                <td>{p.laboratory ?? "not stated"}</td>
                <td>
                  <StatusChip status={p.verification_status} /> {p.has_open_flag && <span className="chip warn">open flag</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Chart({ s }: { s: Series }) {
  const pts = s.points.filter((p) => p.value != null);
  if (pts.length === 0) return null;
  const W = 640, H = 200, L = 48, R = 16, T = 12, B = 28;
  const xs = pts.map((p) => Date.parse(p.collection_date));
  const ys = pts.map((p) => p.value as number);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [yMin, yMax] = [Math.min(...ys), Math.max(...ys)];
  const pad = (yMax - yMin) * 0.15 || Math.abs(yMax) * 0.1 || 1;
  const [y0, y1] = [yMin - pad, yMax + pad];
  const sx = (x: number) => (x1 === x0 ? (L + W - R) / 2 : L + ((x - x0) / (x1 - x0)) * (W - L - R));
  const sy = (y: number) => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
  const accepted = pts.filter((p) => p.verification_status === "accepted");
  const line = accepted.map((p) => `${sx(Date.parse(p.collection_date))},${sy(p.value as number)}`).join(" ");
  const ticks = yMin === yMax ? [yMin] : [yMin, (yMin + yMax) / 2, yMax];

  return (
    <div className="chart" aria-label={`Chart of ${s.label}`}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={sy(t)} y2={sy(t)} stroke="var(--border)" />
            <text x={L - 6} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
              {Number(t.toPrecision(3))}
            </text>
          </g>
        ))}
        {accepted.length > 1 && <polyline points={line} fill="none" stroke="var(--accent)" strokeWidth="1.5" />}
        {pts.map((p) => {
          const cx = sx(Date.parse(p.collection_date));
          const cy = sy(p.value as number);
          const isAccepted = p.verification_status === "accepted";
          return (
            <g key={p.observation_id}>
              <circle cx={cx} cy={cy} r={4.5} fill={isAccepted ? "var(--accent)" : "var(--surface)"} stroke={p.has_open_flag ? "var(--warn)" : "var(--accent)"} strokeWidth={p.has_open_flag ? 2.5 : 1.5}>
                <title>{`${p.collection_date}: ${p.comparator ?? ""}${p.value} ${s.unit ?? ""} (${p.verification_status})`}</title>
              </circle>
              <text x={cx} y={H - 8} textAnchor="middle" fontSize="10" fill="var(--muted)">
                {p.collection_date.slice(0, 7)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

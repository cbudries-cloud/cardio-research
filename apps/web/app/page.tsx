"use client";

// Cardiovascular overview: the record organized by cardiovascular question. Confirmed observations, rows awaiting
// review, interpretations and missing information are kept apart. Implementation status is underneath.

import Link from "next/link";
import { api, type Overview } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ErrorNote, Loading, useLoad } from "@/components/ui";

interface Point {
  observation_id: string; test_as_written: string; value_as_written: string | null; unit: string | null;
  collection_date: string | null; years_ago: number | null; status: string; reported_as: string;
  lab_flag: string | null; reference_range: string | null;
}
interface Series {
  label: string; unit: string | null; collection_method: string; value_origin: string; points: Point[];
  change: { from_date: string; to_date: string; from: string; to: string; difference: number; unit: string; draws: number; note: string } | null;
  comparability: string[];
}
interface Interp {
  source: string; run_id?: string; investigation_id?: string; summary?: string; conclusion_status?: string;
  statements?: { path: string; statement: string; is_inference: boolean; accepted: boolean; flag: string | null; observation_ids: string[] }[];
}
interface Domain {
  id: string; title: string; question: string; state: "measured" | "awaiting_review" | "self_reported" | "unknown";
  series: Series[]; context: { context_id: string; item: string; value: string; as_of: string | null }[];
  missing_context_items: string[]; shows: string[]; cannot_establish: string[]; interpretations: Interp[]; awaiting_review: number;
}
interface CardioOverview {
  as_of: string;
  headline: { shows: string[]; cannot_establish: string[]; deserves_investigation: { id: string; title: string }[] };
  domains: Domain[];
  counts: Record<string, number>;
}

const STATE: Record<Domain["state"], [string, string]> = {
  measured: ["ok", "measured"],
  awaiting_review: ["warn", "only rows awaiting review"],
  self_reported: ["", "self-reported only"],
  unknown: ["bad", "unknown"],
};
const STATUS: Record<string, [string, string]> = {
  confirmed: ["ok", "confirmed"],
  software_checked: ["warn", "software-checked"],
  awaiting_review: ["", "awaiting review"],
  blocked: ["bad", "blocked"],
};

export default function OverviewPage() {
  const { data, error } = useLoad(() => api<CardioOverview>("/research/overview"));
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const h = data.headline;
  return (
    <div className="stack">
      <div>
        <h1>Your cardiovascular record</h1>
        <p className="subtle">
          Private page, as of {data.as_of}. Organized by question, not by report. Confirmed observations support conclusions;
          software-checked and unreviewed rows are shown with their status. Unknown means not in the record, not normal.
        </p>
      </div>

      <section className="split" data-testid="headline">
        <div className="card">
          <h2 style={{ marginTop: 0 }}>What the records show</h2>
          <ul>{h.shows.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
        <div className="card">
          <h2 style={{ marginTop: 0 }}>What they cannot establish</h2>
          <ul>{h.cannot_establish.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      </section>
      <section className="card">
        <h2 style={{ marginTop: 0 }}>What deserves investigation</h2>
        <ol>
          {h.deserves_investigation.map((p) => <li key={p.id}><Link href={`/research#${p.id}`}>{p.title}</Link></li>)}
        </ol>
        <div className="row">
          <Link className="button primary" href="/ask">Ask about the whole record</Link>
          <Link className="button" href="/research">Choose a research question</Link>
          <Link className="button" href="/next">Next investigation</Link>
          <Link className="button" href="/context">Add missing health context</Link>
        </div>
      </section>

      {data.domains.map((d) => <DomainCard key={d.id} d={d} />)}

      <RecordStatus counts={data.counts} />
    </div>
  );
}

function DomainCard({ d }: { d: Domain }) {
  const [cls, label] = STATE[d.state];
  return (
    <section className="card stack" id={d.id} data-testid={`domain-${d.id}`}>
      <div className="row">
        <h2 style={{ margin: 0 }}>{d.title}</h2>
        <span className={`chip ${cls}`}>{label}</span>
        {d.awaiting_review > 0 && <Link className="chip warn" href="/review">{d.awaiting_review} awaiting review</Link>}
      </div>
      <p className="subtle" style={{ margin: 0 }}>{d.question}</p>
      {d.shows.length > 0 && <ul>{d.shows.map((s) => <li key={s}>{s}</li>)}</ul>}
      {d.cannot_establish.length > 0 && (
        <div className="notice">
          <strong>Cannot establish:</strong>
          <ul style={{ margin: "4px 0 0" }}>{d.cannot_establish.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      )}
      {d.series.length > 0 && <MarkerSummary series={d.series} />}
      {d.series.length > 0 && (
        <details>
          <summary>All measurements ({d.series.reduce((n, s) => n + s.points.length, 0)}), by comparable series</summary>
          {d.series.map((s) => <SeriesTable key={`${s.label}|${s.unit}|${s.collection_method}|${s.value_origin}`} s={s} />)}
        </details>
      )}
      {d.missing_context_items.length > 0 && (
        <p className="subtle">
          Missing: {d.missing_context_items.join("; ")}. <Link href="/context">Add it</Link>
        </p>
      )}
      {d.interpretations.map((i, n) => <Interpretation key={n} i={i} />)}
    </section>
  );
}

function MarkerSummary({ series }: { series: Series[] }) {
  // One row per comparable series: the latest usable value, or why none is usable yet.
  return (
    <div className="table-wrap">
      <table data-testid="marker-summary">
        <thead><tr><th>Measure</th><th>Latest usable</th><th>Change (first to last comparable)</th><th>Points</th></tr></thead>
        <tbody>
          {series.map((s) => {
            const usable = s.points.filter((p) => p.status === "confirmed" || p.status === "software_checked");
            const last = usable[usable.length - 1];
            return (
              <tr key={`${s.label}|${s.unit}|${s.collection_method}|${s.value_origin}`}>
                <td>{s.label} <span className="subtle">{s.unit ?? ""}{s.value_origin === "calculated" ? ", calculated" : ""}{s.collection_method === "capillary" ? ", capillary" : ""}</span></td>
                <td>
                  {last ? (
                    <>
                      <Link href={`/observations/${last.observation_id}`}>{last.value_as_written}</Link> on {last.collection_date}{" "}
                      <span className="subtle">({last.years_ago} y ago)</span>{" "}
                      <span className={`chip ${STATUS[last.status][0]}`}>{STATUS[last.status][1]}</span>
                    </>
                  ) : <span className="subtle">none yet; {s.points.length} awaiting review</span>}
                </td>
                <td>{s.change ? `${s.change.from} to ${s.change.to} (${s.change.difference > 0 ? "+" : ""}${s.change.difference}) over ${s.change.draws} draws` : <span className="subtle">fewer than two comparable draws</span>}</td>
                <td>{usable.length} usable{s.points.length > usable.length ? `, ${s.points.length - usable.length} not yet` : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SeriesTable({ s }: { s: Series }) {
  return (
    <div>
      <strong>{s.label}</strong>{" "}
      <span className="subtle">
        {s.unit ?? "no unit"}; {s.value_origin === "calculated" ? "calculated" : s.value_origin === "measured_direct" ? "direct" : "method not stated"};{" "}
        {s.collection_method} collection
      </span>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Collected</th><th>Result</th><th>Lab range and flag</th><th>Status</th></tr></thead>
          <tbody>
            {s.points.map((p) => (
              <tr key={p.observation_id}>
                <td>{p.collection_date ?? "undated"} {p.years_ago != null && <span className="subtle">({p.years_ago} y ago)</span>}</td>
                <td><Link href={`/observations/${p.observation_id}`}>{p.value_as_written ?? "none"} {p.unit}</Link>{p.reported_as !== "current" && <span className="subtle"> reprinted earlier result</span>}</td>
                <td>{p.reference_range ?? "none printed"}{p.lab_flag ? `, flag ${p.lab_flag}` : ""}</td>
                <td><span className={`chip ${STATUS[p.status]?.[0] ?? ""}`}>{STATUS[p.status]?.[1] ?? p.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s.change && (
        <p className="subtle">
          {s.change.from} to {s.change.to} {s.change.unit} ({s.change.difference > 0 ? "+" : ""}{s.change.difference}) between {s.change.from_date} and {s.change.to_date}. {s.change.note}
        </p>
      )}
      {s.comparability.length > 0 && <ul className="subtle">{s.comparability.map((c) => <li key={c}>{c}</li>)}</ul>}
    </div>
  );
}

function Interpretation({ i }: { i: Interp }) {
  return (
    <div className="card" data-testid="interpretation">
      <span className="chip">interpretation</span> <strong>{i.source}</strong>
      {i.summary && <p>{i.summary} {i.investigation_id && <Link href={`/research?inv=${i.investigation_id}`}>Open</Link>}</p>}
      {i.statements && (
        <ul>
          {i.statements.map((s) => (
            <li key={s.path}>
              {s.accepted ? null : <span className="chip bad" title={s.flag ?? ""}>flagged, not accepted</span>} {s.is_inference && <span className="chip">inference</span>}{" "}
              {s.statement}
              {!s.accepted && <span className="subtle"> ({s.flag})</span>}
            </li>
          ))}
        </ul>
      )}
      {i.run_id && <p className="subtle">Model output from an approved run; whether each cited source supports its statement still needs your reading. <Link href="/investigation">Full review</Link></p>}
    </div>
  );
}

function RecordStatus({ counts }: { counts: Record<string, number> }) {
  const { data, error } = useLoad(() => api<Overview>("/overview"));
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const tiles = [
    { n: counts.confirmed ?? 0, l: "Cardiovascular results confirmed by you", href: "/review" },
    { n: counts.software_checked ?? 0, l: "Software-checked, not yet confirmed", href: "/review" },
    { n: data.documents, l: "Source documents", href: "/documents" },
    { n: data.unverified, l: `Candidates awaiting review (${data.unverified_blocked} blocked)`, href: "/review" },
    { n: data.open_flags, l: "Open review flags", href: "/review" },
    { n: data.accepted, l: "Accepted observations (all tests)", href: "/trends" },
  ];
  return (
    <details className="card">
      <summary>Record status and validation</summary>
      <p className="subtle">Last activity: {data.last_activity_at ? formatDateTime(data.last_activity_at) : "none yet"}.
        Only accepted observations without open flags are used; an unresolved item never hides unrelated usable results.</p>
      <div className="grid-tiles">
        {tiles.map((t) => (
          <Link key={t.l} href={t.href} style={{ textDecoration: "none", color: "inherit" }}>
            <div className="card tile"><div className="n">{t.n}</div><div className="l">{t.l}</div></div>
          </Link>
        ))}
      </div>
    </details>
  );
}

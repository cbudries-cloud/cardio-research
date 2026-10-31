"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorNote, Loading, useLoad } from "@/components/ui";

interface ObsRef {
  observation_id: string;
  test_as_written: string;
  value_as_written: string;
  unit: string | null;
  collection_date: string;
  reported_as: string;
  verification_method: string;
  lab_flag: string | null;
  reference_range: string | null;
  laboratory: string | null;
  method: string | null;
  fasting: string | null;
  source: { document_id: string | null; document: string | null; page: number | null; column: string };
}
interface Evidence {
  record: string | null;
  available: boolean;
  citation?: string;
  claims?: { id: string; statement: string; value: number | null; lower: number | null; upper: number | null; unit: string | null; quote: string | null }[];
  applicability_limits?: string[];
  why: string;
}
interface Finding {
  id: string;
  kind: string;
  title: string;
  provisional: boolean;
  confirmation: { observations: number; confirmed_by_participant: number; automated_check_only: number };
  observations: ObsRef[];
  establishes: string[];
  does_not_establish: string[];
  comparability: string[];
  evidence: Evidence[];
  competing_explanations: string[];
  distinguishing_information: string[];
  decision_it_could_change: string;
  interpretation?: string | null;
}
interface Research {
  question: string;
  workflow: { step: string; executor: string; execution?: string; blockers?: string[]; latency_ms?: number; cost_usd?: number | null }[];
  q1_extraction: { role: string; observation_id: string; collection_date: string; verification: string; report: string; page: number; accession: string | null; laboratory_code: string | null; method: string; method_basis: string }[];
  q2_reproducibility_and_interpretability: string[];
  q3_clinical_interpretation: string[];
  hypotheses: { hypothesis: string; supporting: string[]; contrary: string[]; evidence_gaps?: string[]; assumptions: string[]; distinguishing: string[] }[];
  claims: { id: string; text: string; kind: string; depends_on_observations: string[]; depends_on_evidence: string[] }[];
  evidence: { record: string; citation: string; access: string }[];
  applicability: Record<string, string[]>;
  limitations: string[];
  interpretation: { text: string | null; execution: string; provider: string; model: string | null; error: string | null };
}
interface QueueItem { observation_id: string; test_as_written: string; value_as_written: string | null; unit: string | null; collection_date: string | null; reference_range: string | null; lab_flag: string | null; source_status: string; outside_lab_range: boolean }
interface Diff { added: string[]; withdrawn: string[]; changed: string[]; unchanged: string[] }

interface V01 {
    findings: Finding[];
    conventional: Snapshot["outputs"]["conventional"];
    prediction_question: Snapshot["outputs"]["prediction_question"];
    verification_items: ObsRef[];
    unfamiliar_outside_range: ObsRef[];
    possible_name_fragments: ObsRef[][];
    history: Snapshot["outputs"]["history"];
    capabilities: Snapshot["outputs"]["capabilities"];
}

interface Snapshot {
  id: string;
  version: number;
  created_at: string;
  runtime_version: string;
  rules_sha256: string;
  inputs: { observations: unknown[]; excluded: { unverified: number; unverified_blocked: number; open_flags: number } };
  outputs: {
    findings: Finding[];
    conventional: { key: string; label: string; unit: string | null; points: number; dates: string[]; outside_lab_range: number; recognized: boolean; collection_method: string; value_origin: string }[];
    prediction_question: null | { question: string; outcome: string; window: string; comparison_baselines: string[]; scoring: string; comparable_points_available: number; no_forecast_because: string[]; not_initiated: string };
    verification_items: ObsRef[];
    unfamiliar_outside_range: ObsRef[];
    possible_name_fragments: ObsRef[][];
    history: { dates: string[]; current_results: number; historical_results: number };
    capabilities: { working: string[]; manual_or_pending: string[]; not_used: string[] };
    rules_baseline_v01?: V01;
    research_v02?: { verified: Research | null; provisional_preview: Research | null };
    biological_findings?: string[];
    coverage_limitations?: string[];
    readiness_issues?: string[];
    clinician_review_queue?: { group: string; items: QueueItem[]; note: string }[];
    diff_from_previous?: { verified: Diff; provisional_preview: Diff };
    inputs_split?: { verified: number; provisional: number };
  };
}

function List({ items }: { items: string[] }) {
  if (!items.length) return <p className="subtle">None.</p>;
  return (
    <ul>
      {items.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ul>
  );
}

function ObsTable({ rows }: { rows: ObsRef[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Test (as written)</th>
            <th>Value</th>
            <th>Lab range / flag</th>
            <th>Kind</th>
            <th>Verification</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.observation_id}>
              <td>{o.collection_date}</td>
              <td>{o.test_as_written}</td>
              <td>
                {o.value_as_written} {o.unit}
                {o.method ? <span className="subtle"> {o.method}</span> : null}
              </td>
              <td>
                {o.reference_range ?? <span className="subtle">not printed</span>} {o.lab_flag && <span className="chip">{o.lab_flag}</span>}
              </td>
              <td>{o.reported_as === "current" ? "current" : "previous result, reprinted"}</td>
              <td>{o.verification_method === "participant_review" ? "confirmed by you" : <span className="subtle">software-checked</span>}</td>
              <td>
                <Link href={`/observations/${o.observation_id}`}>
                  {o.source.document ?? "manual"}
                  {o.source.page ? `, p. ${o.source.page}` : ""}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FindingCard({ f, n }: { f: Finding; n: number }) {
  return (
    <section className="card stack" id={f.id}>
      <h2 style={{ marginTop: 0 }}>
        {n}. {f.title}
      </h2>
      <p className="subtle">
        {f.kind === "finding" ? "Finding" : "Unresolved question"} ·{" "}
        {f.provisional
          ? `Provisional: ${f.confirmation.automated_check_only} of ${f.confirmation.observations} observation(s) are software-checked only and not yet confirmed by you.`
          : "All observations confirmed by you against their sources."}
      </p>
      {f.interpretation && <div className="notice">{f.interpretation}</div>}
      {f.observations.length > 0 && <ObsTable rows={f.observations} />}
      <h3>What these observations establish</h3>
      <List items={f.establishes} />
      <h3>What they do not establish</h3>
      <List items={f.does_not_establish} />
      {f.comparability.length > 0 && (
        <>
          <h3>Measurement comparability and gaps</h3>
          <List items={f.comparability} />
        </>
      )}
      <h3>Published evidence and its limits</h3>
      {f.evidence.map((e, i) =>
        e.available ? (
          <div key={i}>
            <p>
              <a href={`http://127.0.0.1:3100/entries/${e.record}`} target="_blank" rel="noreferrer">
                {e.citation}
              </a>
              . {e.why}
            </p>
            <List items={(e.claims ?? []).map((c) => `${c.statement} ${c.value ?? ""}${c.lower != null ? `${c.lower}-${c.upper}` : ""} ${c.unit ?? ""}${c.quote ? ` (quote: "${c.quote}")` : ""} [${c.id}]`)} />
            <p className="subtle">Applicability limits:</p>
            <List items={e.applicability_limits ?? []} />
          </div>
        ) : (
          <p key={i} className="subtle">
            {e.why}
          </p>
        ),
      )}
      <h3>Plausible competing explanations</h3>
      <List items={f.competing_explanations} />
      <h3>What could distinguish them</h3>
      <List items={f.distinguishing_information} />
      <h3>Decision this could change</h3>
      <p>{f.decision_it_could_change}</p>
    </section>
  );
}

export default function BaselinePage() {
  const { data, error, reload } = useLoad(() => api<{ version: number }[]>("/research/snapshots"), []);
  const latest = data?.[0]?.version;
  const snap = useLoad(() => (latest ? api<Snapshot>(`/research/snapshots/${latest}`) : Promise.resolve(null)), [latest]);
  const [busy, setBusy] = useState(false);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  async function create() {
    setBusy(true);
    try {
      await api("/research/snapshots", { method: "POST" });
      reload();
    } finally {
      setBusy(false);
    }
  }

  const raw = snap.data;
  const s = raw && raw.outputs.rules_baseline_v01 ? { ...raw, outputs: { ...raw.outputs, ...raw.outputs.rules_baseline_v01 } } : raw;
  const v2 = raw?.outputs.research_v02;
  return (
    <div className="stack">
      <div>
        <h1>Personal baseline</h1>
        <p className="subtle">
          Private. Generated inside this application by the research runtime from accepted observations only. Not for
          publication. Not a diagnosis, a risk estimate or a recommendation.
        </p>
        <div className="row">
          <button className="primary" onClick={create} disabled={busy}>
            {busy ? "Creating…" : "Create new snapshot from current records"}
          </button>
          {data.length > 0 && <span className="subtle">{data.length} snapshot(s); showing the latest.</span>}
        </div>
      </div>
      {!s ? (
        <p className="subtle">No snapshot yet.</p>
      ) : (
        <>
          <div className="card">
            <p>
              Snapshot v{s.version} · {new Date(s.created_at).toLocaleString()} · runtime {s.runtime_version} · rules{" "}
              <span className="mono">{s.rules_sha256.slice(0, 12)}</span>
            </p>
            <p>
              {s.inputs.observations.length} accepted observations ({s.outputs.history.current_results} current,{" "}
              {s.outputs.history.historical_results} previous results reprinted in later reports) from{" "}
              {s.outputs.history.dates.length} collection date(s): {s.outputs.history.dates.join(", ")}. Excluded:{" "}
              {s.inputs.excluded.unverified} unverified ({s.inputs.excluded.unverified_blocked} blocked), {s.inputs.excluded.open_flags}{" "}
              open review flag(s).
            </p>
          </div>

          {v2 && <ResearchV02 outputs={raw!.outputs} />}

          <h2>Rules-based baseline v0.1 ({s.outputs.findings.length}) <span className="subtle">(preserved for comparison; fixed rules, no model)</span></h2>
          {s.outputs.findings.map((f, i) => (
            <FindingCard key={f.id} f={f} n={i + 1} />
          ))}

          <h2>Everything else: conventional, no further question raised</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Unit</th>
                  <th>Series</th>
                  <th>Points</th>
                  <th>Dates</th>
                  <th>Outside lab range</th>
                </tr>
              </thead>
              <tbody>
                {s.outputs.conventional.map((c) => (
                  <tr key={`${c.key}-${c.unit}-${c.collection_method}-${c.value_origin}`}>
                    <td>
                      {c.label}
                      {!c.recognized && <span className="subtle"> (unfamiliar, kept)</span>}
                    </td>
                    <td>{c.unit}</td>
                    <td className="subtle">
                      {c.collection_method}, {c.value_origin.replace("_", " ")}
                    </td>
                    <td>{c.points}</td>
                    <td>{c.dates.join(", ")}</td>
                    <td>{c.outside_lab_range || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2>Outside the laboratory range, not interpreted ({s.outputs.unfamiliar_outside_range.length})</h2>
          <p className="subtle">
            Tests outside this project&apos;s cardiovascular dictionary that the laboratory flagged or printed outside its
            range. They are preserved and listed, but the runtime has no verified evidence to interpret them; they are
            questions for clinical review, not findings.
          </p>
          {s.outputs.unfamiliar_outside_range.length > 0 && <ObsTable rows={s.outputs.unfamiliar_outside_range} />}

          <h2>First testable question (no forecast made)</h2>
          {s.outputs.prediction_question ? (
            <div className="card stack">
              <p>
                <strong>{s.outputs.prediction_question.question}</strong>
              </p>
              <p>Outcome: {s.outputs.prediction_question.outcome}</p>
              <p>Window: {s.outputs.prediction_question.window}</p>
              <p>Comparison baselines:</p>
              <List items={s.outputs.prediction_question.comparison_baselines} />
              <p>Scoring: {s.outputs.prediction_question.scoring}</p>
              <p>Why no numerical forecast yet:</p>
              <List items={s.outputs.prediction_question.no_forecast_because} />
              <p className="subtle">{s.outputs.prediction_question.not_initiated}</p>
            </div>
          ) : (
            <p className="subtle">Not enough comparable lipid measurements to frame one.</p>
          )}

          <h2>Unresolved verification items ({s.outputs.verification_items.length})</h2>
          <p className="subtle">
            Observations the investigation relies on that were checked by software but not yet by you. Open each, compare
            with the source, and choose &quot;Confirm against source&quot;; then create a new snapshot.
          </p>
          <ObsTable rows={s.outputs.verification_items} />

          {s.outputs.possible_name_fragments.length > 0 && (
            <>
              <h2>Possible split test names ({s.outputs.possible_name_fragments.length})</h2>
              <p className="subtle">
                Different test names with the same value, unit and date. A long name wrapped across lines in the report
                may have been read as two tests. Check each against the source.
              </p>
              <ObsTable rows={s.outputs.possible_name_fragments.flat()} />
            </>
          )}

          <h2>What the runtime did</h2>
          <div className="card">
            <p>Working:</p>
            <List items={s.outputs.capabilities.working} />
            <p>Manual or pending:</p>
            <List items={s.outputs.capabilities.manual_or_pending} />
            <p>Not used:</p>
            <List items={s.outputs.capabilities.not_used} />
          </div>
        </>
      )}
    </div>
  );
}

function ResearchPanel({ r, label }: { r: Research | null; label: string }) {
  if (!r) return <p className="subtle">{label}: no LDL particle number among these inputs.</p>;
  return (
    <div className="stack">
      <p className="subtle">{label}</p>
      <p><strong>Question:</strong> {r.question}</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Workflow step</th><th>Executor</th><th>Execution / blockers</th></tr></thead>
          <tbody>
            {r.workflow.map((w) => (
              <tr key={w.step}>
                <td>{w.step}</td>
                <td>{w.executor}</td>
                <td>{w.execution ?? ""} {(w.blockers ?? []).join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>1. Is each observation accurately extracted?</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Role</th><th>Date</th><th>Report, page</th><th>Accession</th><th>Lab code</th><th>Method named in report</th><th>Verification</th><th></th></tr></thead>
          <tbody>
            {r.q1_extraction.map((x) => (
              <tr key={x.observation_id}>
                <td>{x.role}</td><td>{x.collection_date}</td><td>{x.report}, p. {x.page}</td><td>{x.accession ?? "not printed"}</td>
                <td>{x.laboratory_code}</td><td>{x.method.replaceAll("_", " ")}</td>
                <td>{x.verification === "participant_review" ? "confirmed by you" : "software-checked only"}</td>
                <td><Link href={`/observations/${x.observation_id}`}>Review / confirm</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>2. Is the difference reproducible and analytically interpretable?</h3>
      <List items={r.q2_reproducibility_and_interpretability} />
      <h3>3. Does it change clinical risk interpretation?</h3>
      <List items={r.q3_clinical_interpretation} />
      <h3>Competing explanations</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Hypothesis</th><th>Supporting</th><th>Contrary</th><th>Evidence gaps</th><th>Unresolved assumptions</th><th>Would distinguish</th></tr></thead>
          <tbody>
            {r.hypotheses.map((h) => (
              <tr key={h.hypothesis}>
                <td>{h.hypothesis}</td><td><List items={h.supporting} /></td><td><List items={h.contrary} /></td><td><List items={h.evidence_gaps ?? []} /></td>
                <td><List items={h.assumptions} /></td><td><List items={h.distinguishing} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Evidence used</h3>
      <List items={r.evidence.map((e) => `${e.citation} [${e.record}] (${e.access})`)} />
      <h3>Applicability limits</h3>
      <List items={Object.entries(r.applicability).flatMap(([k, v]) => v.map((x) => `${k}: ${x}`))} />
      <h3>Limitations of this investigation</h3>
      <List items={r.limitations} />
      <h3>Source-linked interpretation <span className="chip">{r.interpretation.execution}</span></h3>
      <p>{r.interpretation.text}</p>
      <details>
        <summary>Claims and what each depends on ({r.claims.length})</summary>
        <List items={r.claims.map((c) => `${c.text} [${c.id}; observations: ${c.depends_on_observations.length}; evidence: ${c.depends_on_evidence.join(", ") || "none"}]`)} />
      </details>
    </div>
  );
}

function ResearchV02({ outputs }: { outputs: Snapshot["outputs"] }) {
  const v2 = outputs.research_v02!;
  const diff = outputs.diff_from_previous?.provisional_preview;
  return (
    <section className="card stack">
      <h2 style={{ marginTop: 0 }}>Research workflow v0.2: ApoB vs LDL particle number</h2>
      <p className="subtle">
        Inputs: {outputs.inputs_split?.verified} confirmed by you, {outputs.inputs_split?.provisional} software-checked only. The
        verified analysis uses confirmed observations only; the preview uses all accepted observations and is provisional.
      </p>
      <ResearchPanel r={v2.verified} label="Verified analysis (participant-confirmed inputs only)" />
      <ResearchPanel r={v2.provisional_preview} label="Provisional preview (includes software-checked inputs; not a verified result)" />
      {diff && (
        <p className="subtle">
          Since the previous snapshot: {diff.added.length} claim(s) added, {diff.withdrawn.length} withdrawn,{" "}
          {diff.changed.length} changed, {diff.unchanged.length} unchanged.
        </p>
      )}
      <h3>Evidence coverage limitations (not biological findings)</h3>
      <List items={outputs.coverage_limitations ?? []} />
      <h3>Readiness issues (not risk findings)</h3>
      <List items={outputs.readiness_issues ?? []} />
      <h3>Clinician-review queue (outside the research scope)</h3>
      {(outputs.clinician_review_queue ?? []).map((g) => (
        <div key={g.group}>
          <p><strong>{g.group}</strong>. <span className="subtle">{g.note}</span></p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>Test</th><th>Value</th><th>Lab range / flag</th><th>Outside range</th><th>Source status</th></tr></thead>
              <tbody>
                {g.items.map((i) => (
                  <tr key={i.observation_id}>
                    <td>{i.collection_date}</td>
                    <td><Link href={`/observations/${i.observation_id}`}>{i.test_as_written}</Link></td>
                    <td>{i.value_as_written} {i.unit}</td><td>{i.reference_range} {i.lab_flag}</td>
                    <td>{i.outside_lab_range ? "yes" : "no"}</td><td>{i.source_status.replaceAll("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  );
}

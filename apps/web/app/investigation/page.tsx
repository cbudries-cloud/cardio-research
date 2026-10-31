"use client";

// ApoB / LDL-P investigation: confirm the supporting observations against their sources, read the
// exact outgoing request, approve it for one run, and read the live output beside the rules-based one.

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, post, type ObservationDetail } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { ErrorNote, Loading, useLoad } from "@/components/ui";
import { SourceView } from "@/components/SourceView";

interface Gate { id: string; ok: boolean; detail: string }
interface Readiness {
  available: boolean;
  supporting: { observation_id: string; role: string; verification_method: string }[];
  fragment_groups: { observation_ids: string[]; affects_investigation: boolean }[];
  gates: Gate[];
  provider: { name: string | null; model: string | null; endpoint: string | null; key_configured: boolean; blockers: string[] };
  ready_to_prepare: boolean;
}
interface Statement { statement: string; is_inference?: boolean; observation_refs: string[]; evidence_refs: string[]; rule_refs: string[] }
interface Output {
  input_issues: Statement[];
  established: Statement[];
  competing_explanations: {
    explanation: string; relation_to_supplied: string; rule_refs: string[];
    supporting: Statement[]; contrary: Statement[]; evidence_gaps: Statement[]; assessment: Statement;
  }[];
  remaining_uncertainty: Statement[];
  distinguishing_information: { information: string; explanations_distinguished: string[]; evidence_refs: string[] }[];
  comparison_with_rules: { differences_from_rules: Statement[]; unchanged: Statement[] };
}
interface Run {
  id: string;
  status: "awaiting_approval" | "running" | "succeeded" | "failed" | "withdrawn";
  created_at: string;
  snapshot_id: string;
  snapshot_version: number | null;
  provider: string;
  model: string;
  endpoint: string;
  request_body: { messages: { content: string }[] } & Record<string, unknown>;
  payload_sha256: string;
  evidence_ids: string[];
  estimate: Record<string, unknown> & { cost_usd_typical: number; cost_usd_max: number; input_tokens_upper_estimate: number; max_output_tokens: number; basis: string };
  limits: Record<string, string | number>;
  data_handling: { setting: string; text: string; source: string }[];
  approval: Record<string, unknown> | null;
  approved_at: string | null;
  completed_at: string | null;
  response_id: string | null;
  response_model: string | null;
  stop_reason: string | null;
  usage: Record<string, number> | null;
  cost_usd: number | null;
  latency_ms: number | null;
  output: Output | null;
  citation_check: { statements: number; uncited: string[]; unknown_refs: { path: string; ref: string }[]; established_without_observation_or_evidence: string[]; supported_only_by_rule_refs: string[]; inferences: number; input_issues: number; scope_flags: string[]; structurally_valid: boolean; note: string } | null;
  comparison: { rule_refs_engaged: string[]; rule_refs_not_engaged: string[]; evidence_cited_beyond_rules: string[]; rules_explanations: number; live_explanations: number } | null;
  error: string | null;
}
interface Payload {
  observations: { ref: string; role: string; test_as_written: string; value_as_written: string; unit: string; timing: string }[];
  rules_based_interpretation: { claims: { ref: string; kind: string; text: string }[]; hypotheses: { ref: string; hypothesis: string; supporting: string[]; contrary: string[] }[] };
  evidence: { id: string; title: string; claims: { ref: string; statement: string; quote?: string }[] }[];
  laboratory_documentation: { ref: string; test: string }[];
}

const payloadOf = (run: Run): Payload => JSON.parse(run.request_body.messages[0].content.split("\n").slice(1).join("\n"));

export default function InvestigationPage() {
  const ready = useLoad(() => api<Readiness>("/research/apob-ldlp/readiness"));
  const runs = useLoad(() => api<{ id: string; status: string; created_at: string; model: string; snapshot_version: number | null }[]>("/research/live-runs"));
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = selected ?? runs.data?.[0]?.id ?? null;

  async function prepare() {
    setError(null);
    try {
      const run = await post<Run>("/research/live-runs", {});
      setSelected(run.id);
      runs.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (ready.error) return <ErrorNote error={ready.error} />;
  if (!ready.data) return <Loading />;
  const r = ready.data;

  return (
    <div className="stack">
      <div>
        <h1>ApoB / LDL particle number: live investigation</h1>
        <p className="subtle">
          Private page. One live model run, only after you confirm the observations it uses and approve the exact request.
          Nothing here orders tests, recommends treatment or estimates your risk.
        </p>
      </div>

      <section className="card stack">
        <h2 style={{ marginTop: 0 }}>1. Confirm the supporting observations against their sources</h2>
        {!r.available && <div className="notice warn">{r.gates[0]?.detail}</div>}
        <Gates gates={r.gates} />
        {r.supporting.map((s) => (
          <ConfirmItem key={s.observation_id} id={s.observation_id} role={s.role} onChange={ready.reload} />
        ))}
        {r.fragment_groups.length > 0 && (
          <>
            <h3>Possible split test names ({r.fragment_groups.length}, unresolved)</h3>
            <p className="subtle">Shown for completeness. Only a group on the investigation&apos;s draw that could belong to its inputs blocks this run.</p>
            <ul>
              {r.fragment_groups.map((g, i) => (
                <li key={i}>
                  {g.affects_investigation ? <span className="chip bad">could affect inputs</span> : <span className="chip">does not affect this run</span>}{" "}
                  {g.observation_ids.map((id, j) => (
                    <span key={id}>
                      {j > 0 && ", "}
                      <Link href={`/observations/${id}`}>record {j + 1}</Link>
                    </span>
                  ))}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="card stack">
        <h2 style={{ marginTop: 0 }}>2. Provider</h2>
        <table>
          <tbody>
            <tr><th>Provider</th><td>{r.provider.name ?? "none"}</td></tr>
            <tr><th>Model</th><td>{r.provider.model ?? "not set"}</td></tr>
            <tr><th>Endpoint</th><td><code>{r.provider.endpoint}</code></td></tr>
            <tr><th>API key</th><td>{r.provider.key_configured ? "key file present (the key is never shown or sent to the browser)" : "not configured"}</td></tr>
          </tbody>
        </table>
        {r.provider.blockers.map((b) => <div key={b} className="notice warn">{b}</div>)}
        <div className="row">
          <button className="primary" disabled={!r.ready_to_prepare} onClick={prepare}>Prepare a live run for approval</button>
          <span className="subtle">Takes a new snapshot of confirmed observations and builds the request. Nothing is sent.</span>
        </div>
        <ErrorNote error={error} />
      </section>

      {runs.data && runs.data.length > 1 && (
        <div className="row">
          <span className="subtle">Runs:</span>
          {runs.data.map((x) => (
            <button key={x.id} onClick={() => setSelected(x.id)} className={x.id === current ? "primary" : ""}>
              {new Date(x.created_at).toLocaleString()} ({x.status.replace("_", " ")})
            </button>
          ))}
        </div>
      )}
      {current && <RunView id={current} providerReady={r.provider.blockers.length === 0} onChange={runs.reload} />}
    </div>
  );
}

function Gates({ gates }: { gates: Gate[] }) {
  return (
    <ul>
      {gates.map((g) => (
        <li key={g.id}>
          <span className={`chip ${g.ok ? "ok" : "warn"}`}>{g.ok ? "ready" : "not ready"}</span> {g.detail}
        </li>
      ))}
    </ul>
  );
}

function ConfirmItem({ id, role, onChange }: { id: string; role: string; onChange: () => void }) {
  const { data, error, reload } = useLoad(() => api<ObservationDetail>(`/observations/${id}`), [id]);
  const [checked, setChecked] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const o = data.observation;
  const confirmed = o.verification_method === "participant_review";
  async function confirm() {
    setErr(null);
    try {
      await post(`/observations/${id}/confirm`, { confirm_source_matches: true, note: "confirmed for the ApoB/LDL-P investigation" });
      reload();
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <div className="card stack" data-testid="confirm-item">
      <div className="row">
        <strong>{role}</strong>
        <span>{o.original_test_name}</span>
        <span>{formatValue(o.original_value, o.original_unit)}</span>
        <span className="subtle">range {o.reference_range_raw ?? "none printed"}{o.lab_flag_raw ? `, flag ${o.lab_flag_raw}` : ""}, collected {o.collection_date}</span>
        <span className={`chip ${confirmed ? "ok" : "warn"}`}>{confirmed ? "confirmed by you" : "software-checked only"}</span>
        <button onClick={() => setOpen(!open)}>{open ? "Hide source" : "Show source"}</button>
      </div>
      {open && <SourceView document={data.document} location={o.source_location} />}
      {!confirmed && (
        <div className="row">
          <label className="row" style={{ color: "inherit", fontSize: 14 }}>
            <input type="checkbox" checked={checked} disabled={!open} onChange={(e) => setChecked(e.target.checked)} />
            I compared the name, value, unit, range and date above with the source and they match.
          </label>
          <button className="primary" disabled={!checked || !open} onClick={confirm}>Confirm against source</button>
          {!open && <span className="subtle">Open the source first.</span>}
        </div>
      )}
      <ErrorNote error={err} />
    </div>
  );
}

function RunView({ id, providerReady, onChange }: { id: string; providerReady: boolean; onChange: () => void }) {
  const { data: run, error, reload } = useLoad(() => api<Run>(`/research/live-runs/${id}`), [id]);
  useEffect(() => {
    if (run?.status !== "running") return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [run?.status, reload]);
  if (error) return <ErrorNote error={error} />;
  if (!run) return <Loading />;
  const payload = payloadOf(run);
  return (
    <>
      <Approval run={run} providerReady={providerReady} onChange={() => { reload(); onChange(); }} />
      {(run.status === "running" || run.status === "succeeded" || run.status === "failed") && <Result run={run} payload={payload} />}
    </>
  );
}

function Approval({ run, providerReady, onChange }: { run: Run; providerReady: boolean; onChange: () => void }) {
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pending = run.status === "awaiting_approval";
  async function act(path: string, body: unknown) {
    setErr(null);
    try {
      await post(path, body);
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <section className="card stack" data-testid="approval">
      <h2 style={{ marginTop: 0 }}>3. Approval{pending ? "" : `: ${run.status.replace("_", " ")}`}</h2>
      <table>
        <tbody>
          <tr><th>Provider / model</th><td>{run.provider} / <code>{run.model}</code></td></tr>
          <tr><th>Endpoint</th><td><code>{run.endpoint}</code></td></tr>
          <tr><th>Snapshot</th><td>v{run.snapshot_version} (<code>{run.snapshot_id}</code>), confirmed observations only</td></tr>
          <tr><th>Evidence included</th><td>{run.evidence_ids.join(", ")} and the laboratory documentation record</td></tr>
          <tr><th>Estimated cost</th><td>about ${run.estimate.cost_usd_typical.toFixed(2)}; at most ${run.estimate.cost_usd_max.toFixed(2)} (input up to {run.estimate.input_tokens_upper_estimate} tokens, output capped at {run.estimate.max_output_tokens}). <span className="subtle">{run.estimate.basis}</span></td></tr>
          <tr><th>Execution limits</th><td>{Object.entries(run.limits).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join("; ")}</td></tr>
          <tr><th>Payload SHA-256</th><td><code>{run.payload_sha256}</code></td></tr>
        </tbody>
      </table>
      <h3>Data handling at this provider</h3>
      <ul>
        {run.data_handling.map((d) => (
          <li key={d.setting}><strong>{d.setting}.</strong> {d.text} <a href={d.source} target="_blank" rel="noreferrer">source</a></li>
        ))}
      </ul>
      <div className="notice">
        Excluded: names, birth date, addresses, accession numbers, document names and paths, record IDs, laboratory codes,
        calendar dates and measurements the investigation does not use. Timing is relative. The remaining health data is
        not anonymous: it is your laboratory results.
      </div>
      <details open={pending}>
        <summary>Exact outgoing request (everything sent except the API key header)</summary>
        <pre style={{ whiteSpace: "pre-wrap", maxHeight: 520, overflow: "auto", fontSize: 12 }}>{JSON.stringify(run.request_body, null, 1)}</pre>
      </details>
      {pending && (
        <>
          {!providerReady && <div className="notice warn">The provider is not ready (see section 2). The request can be read but not sent.</div>}
          <label className="row" style={{ color: "inherit", fontSize: 14 }}>
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            I approve sending exactly this request, once, to {run.provider} {run.model} at {run.endpoint}. This approval does
            not apply to any other run, provider, model, data scope or scheduled run.
          </label>
          <div className="row">
            <button
              className="primary"
              disabled={!ack || !providerReady}
              onClick={() => act(`/research/live-runs/${run.id}/approve`, {
                payload_sha256: run.payload_sha256, provider: run.provider, model: run.model, endpoint: run.endpoint,
                approve_this_payload_for_this_run_only: true,
              })}
            >
              Approve and send once
            </button>
            <button className="danger" onClick={() => act(`/research/live-runs/${run.id}/withdraw`, {})}>Withdraw</button>
          </div>
        </>
      )}
      {run.approval && <p className="subtle">Approved {run.approved_at && new Date(run.approved_at).toLocaleString()}: {String(run.approval.statement)}</p>}
      <ErrorNote error={err} />
    </section>
  );
}

function Refs({ s, payload }: { s: Partial<Statement>; payload: Payload }) {
  const obs = new Map(payload.observations.map((o) => [o.ref, `${o.test_as_written} ${o.value_as_written} ${o.unit} (${o.timing})`]));
  const ev = new Map<string, string>();
  payload.evidence.forEach((e) => {
    ev.set(e.id, e.title);
    e.claims.forEach((c) => ev.set(c.ref, c.quote ? `"${c.quote}"` : c.statement));
  });
  payload.laboratory_documentation.forEach((d) => ev.set(d.ref, d.test));
  const rules = new Map<string, string>([
    ...payload.rules_based_interpretation.claims.map((c) => [c.ref, c.text] as [string, string]),
    ...payload.rules_based_interpretation.hypotheses.map((h) => [h.ref, h.hypothesis] as [string, string]),
  ]);
  const all = [
    ...(s.observation_refs ?? []).map((r) => [r, obs.get(r)] as const),
    ...(s.evidence_refs ?? []).map((r) => [r, ev.get(r)] as const),
    ...(s.rule_refs ?? []).map((r) => [r, rules.get(r)] as const),
  ];
  if (all.length === 0) return <span className="chip warn">no citation</span>;
  return (
    <span className="chips">
      {all.map(([r, label]) => (
        <span key={r} className={`chip ${label ? "" : "bad"}`} title={label ?? "not in the approved payload"}>{r}</span>
      ))}
    </span>
  );
}

function StatementList({ items, payload }: { items: Statement[]; payload: Payload }) {
  if (items.length === 0) return <p className="subtle">None.</p>;
  return (
    <ul>
      {items.map((s, i) => (
        <li key={i}>{s.is_inference && <span className="chip">inference</span>} {s.statement} <Refs s={s} payload={payload} /></li>
      ))}
    </ul>
  );
}

function Result({ run, payload }: { run: Run; payload: Payload }) {
  const o = run.output;
  const c = run.citation_check;
  return (
    <section className="card stack" data-testid="result">
      <h2 style={{ marginTop: 0 }}>4. Live result</h2>
      <table>
        <tbody>
          <tr><th>Execution</th><td>{run.status === "succeeded" ? "live call completed" : run.status === "running" ? "running (refreshes every 3 s)" : `failed: ${run.error}`}</td></tr>
          <tr><th>Model reported</th><td>{run.response_model ?? "none"} {run.response_id && <span className="subtle">({run.response_id})</span>}</td></tr>
          <tr><th>Usage</th><td>{run.usage ? Object.entries(run.usage).filter(([, v]) => typeof v === "number").map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join("; ") : "none"}</td></tr>
          <tr><th>Cost</th><td>{run.cost_usd != null ? `$${run.cost_usd.toFixed(4)}` : "none"}; stop reason {run.stop_reason ?? "none"}; latency {run.latency_ms ? `${(run.latency_ms / 1000).toFixed(1)} s` : "none"}</td></tr>
        </tbody>
      </table>
      {c && (
        <div className={`notice ${c.structurally_valid && c.scope_flags.length === 0 ? "ok" : "warn"}`}>
          Citation check: {c.statements} statements; {c.unknown_refs.length} citation(s) not in the approved payload;{" "}
          {c.uncited.length} uncited; {c.established_without_observation_or_evidence.length} &quot;established&quot; statement(s)
          without an observation or evidence citation; {c.supported_only_by_rule_refs.length} supporting, contrary or assessment
          statement(s) resting only on rule refs; {c.inferences} marked as inference; scope flags: {c.scope_flags.length ? c.scope_flags.join(", ") : "none"}. {c.note}
          {" "}Hover a citation to read the quote.
        </div>
      )}
      {o && (
        <>
          <h3>Problems found in the supplied packet</h3>
          <StatementList items={o.input_issues} payload={payload} />
          <h3>What the observations establish</h3>
          <StatementList items={o.established} payload={payload} />
          <h3>Competing explanations</h3>
          {o.competing_explanations.map((e, i) => (
            <div key={i} className="card">
              <strong>{e.explanation}</strong> <span className="subtle">({e.relation_to_supplied})</span> <Refs s={{ rule_refs: e.rule_refs }} payload={payload} />
              <p className="subtle">Supporting</p>
              <StatementList items={e.supporting} payload={payload} />
              <p className="subtle">Contrary</p>
              <StatementList items={e.contrary} payload={payload} />
              <p className="subtle">Evidence gaps</p>
              <StatementList items={e.evidence_gaps} payload={payload} />
              <p className="subtle">Assessment</p>
              <StatementList items={[e.assessment]} payload={payload} />
            </div>
          ))}
          <h3>Remaining uncertainty</h3>
          <StatementList items={o.remaining_uncertainty} payload={payload} />
          <h3>Information that could distinguish the explanations</h3>
          <ul>
            {o.distinguishing_information.map((d, i) => (
              <li key={i}>{d.information} <span className="subtle">({d.explanations_distinguished.join("; ")})</span> <Refs s={{ evidence_refs: d.evidence_refs }} payload={payload} /></li>
            ))}
          </ul>
          <h3>Compared with the rules-based interpretation</h3>
          <div className="split">
            <div>
              <p className="subtle">Rules-based (deterministic, in the snapshot)</p>
              <ul>
                {payload.rules_based_interpretation.claims.map((x) => <li key={x.ref}><code>{x.ref}</code> {x.text}</li>)}
                {payload.rules_based_interpretation.hypotheses.map((h) => <li key={h.ref}><code>{h.ref}</code> {h.hypothesis}</li>)}
              </ul>
            </div>
            <div>
              <p className="subtle">Differences from the rules</p>
              <StatementList items={o.comparison_with_rules.differences_from_rules} payload={payload} />
              <p className="subtle">Unchanged</p>
              <StatementList items={o.comparison_with_rules.unchanged} payload={payload} />
              {run.comparison && (
                <p className="subtle">
                  Rules engaged: {run.comparison.rule_refs_engaged.join(", ") || "none"}; not engaged: {run.comparison.rule_refs_not_engaged.join(", ") || "none"};
                  evidence cited beyond the rules: {run.comparison.evidence_cited_beyond_rules.join(", ") || "none"};
                  explanations {run.comparison.rules_explanations} (rules) vs {run.comparison.live_explanations} (live).
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

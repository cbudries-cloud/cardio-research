"use client";

// Shared pieces for research-partner runs (questions and investigations): the per-run approval panel, cited
// statements with their refs resolved to local records, and polling while a run executes. Approval is the same
// per-run, single-use approval as the ApoB / LDL-P page (D-050).

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { ErrorNote, Loading, useLoad } from "@/components/ui";

export interface Statement {
  statement: string;
  is_inference: boolean;
  observation_refs: string[];
  context_refs: string[];
  evidence_refs: string[];
  prior_refs: string[];
}
export interface RefInfo { kind: string; id: string; label: string; url?: string; quote?: string; abstract?: string; status?: string }
export interface CitationCheck {
  statements: number;
  uncited: string[];
  unknown_refs: { path: string; ref: string }[];
  established_without_record_or_evidence: string[];
  established_on_unconfirmed_observations: string[];
  established_on_flagged_prior: string[];
  inferences: number;
  scope_flags: string[];
  structurally_valid: boolean;
  note: string;
}
export interface Retrieval {
  domains: string[];
  observation_ids: string[];
  context_ids: string[];
  period: { first: string; last: string; draw_dates: number } | null;
  not_sent_awaiting_review: number;
  unknown_domains: string[];
}
export interface PartnerRun {
  id: string;
  kind: "conversation" | "investigation" | "apob_ldlp";
  status: "awaiting_approval" | "running" | "succeeded" | "failed" | "withdrawn";
  created_at: string;
  completed_at: string | null;
  provider: string;
  model: string;
  endpoint: string;
  payload_sha256: string;
  request_body: Record<string, unknown>;
  evidence_ids: string[];
  estimate: { cost_usd_typical: number; cost_usd_max: number; input_tokens_upper_estimate: number; max_output_tokens: number; basis: string };
  limits: Record<string, string | number>;
  data_handling: { setting: string; text: string; source: string }[];
  approval: Record<string, unknown> | null;
  approved_at: string | null;
  cost_usd: number | null;
  usage: Record<string, number> | null;
  output: Record<string, any> | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  citation_check: CitationCheck | null;
  error: string | null;
  context: { retrieval?: Retrieval; version?: number; investigation_id?: string; search?: { queries: string[]; status: string; pmids: string[] } } & Record<string, unknown>;
  refs: Record<string, RefInfo>;
}

export function useRun(id: string | null) {
  const res = useLoad(() => (id ? api<PartnerRun>(`/research/runs/${id}`) : Promise.resolve(null)), [id]);
  useEffect(() => {
    if (res.data?.status !== "running") return;
    const t = setInterval(res.reload, 3000);
    return () => clearInterval(t);
  }, [res.data?.status, res.reload]);
  return res;
}

export function RefChips({ s, refs }: { s: Partial<Statement>; refs: Record<string, RefInfo> }) {
  const all = [...(s.observation_refs ?? []), ...(s.context_refs ?? []), ...(s.evidence_refs ?? []), ...(s.prior_refs ?? [])];
  if (all.length === 0) return <span className="chip warn">no citation</span>;
  return (
    <span className="chips">
      {all.map((r) => {
        const info = refs[r];
        if (!info) return <span key={r} className="chip bad" title="not in the approved request">{r}</span>;
        const title = [info.label, info.quote && `"${info.quote}"`, info.status].filter(Boolean).join(" | ");
        if (info.kind === "observation") return <Link key={r} className="chip" title={title} href={`/observations/${info.id}`}>{r}: {info.label}</Link>;
        if (info.kind === "context") return <Link key={r} className="chip" title={title} href="/context">{r}: {info.label}</Link>;
        if (info.url) return <a key={r} className="chip warn" title={`${title} (abstract only, unverified)`} href={info.url} target="_blank" rel="noreferrer">{r}</a>;
        return <span key={r} className={`chip ${info.kind === "prior" && info.status?.startsWith("FLAGGED") ? "bad" : ""}`} title={title}>{r}</span>;
      })}
    </span>
  );
}

export function Statements({ items, refs, empty = "None." }: { items: Statement[] | undefined; refs: Record<string, RefInfo>; empty?: string }) {
  if (!items || items.length === 0) return <p className="subtle">{empty}</p>;
  return (
    <ul>
      {items.map((s, i) => (
        <li key={i}>
          {s.is_inference && <span className="chip">inference</span>} {s.statement} <RefChips s={s} refs={refs} />
        </li>
      ))}
    </ul>
  );
}

export function CheckNotice({ c }: { c: CitationCheck | null }) {
  if (!c) return null;
  const problems = [
    c.unknown_refs.length && `${c.unknown_refs.length} citation(s) not in the approved request`,
    c.established_without_record_or_evidence.length && `${c.established_without_record_or_evidence.length} established statement(s) without a record or evidence`,
    c.established_on_unconfirmed_observations.length && `${c.established_on_unconfirmed_observations.length} established statement(s) resting on software-checked (unconfirmed) observations`,
    c.established_on_flagged_prior.length && `${c.established_on_flagged_prior.length} established statement(s) resting on a flagged earlier finding`,
    c.scope_flags.length && `scope flags: ${c.scope_flags.join(", ")}`,
  ].filter(Boolean);
  return (
    <div className={`notice ${problems.length ? "warn" : "ok"}`} data-testid="citation-check">
      Citation check: {c.statements} statements, {c.inferences} marked as inference, {c.uncited.length} uncited.{" "}
      {problems.length ? `Needs your reading: ${problems.join("; ")}.` : "Every citation is in the approved request."} {c.note}
    </div>
  );
}

export function Approval({ run, onChange, purpose }: { run: PartnerRun; onChange: () => void; purpose: string }) {
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
  if (!pending) {
    return (
      <p className="subtle" data-testid="run-status">
        {run.status === "running" ? "Sent; waiting for the answer (refreshes every 3 s)." :
          run.status === "failed" ? `Failed: ${run.error}. Nothing was retried.` :
          run.status === "withdrawn" ? "Withdrawn; nothing was sent." :
          `Answered ${run.completed_at ? new Date(run.completed_at).toLocaleString() : ""} by ${run.model}; cost $${run.cost_usd?.toFixed(3) ?? "?"}.`}
      </p>
    );
  }
  return (
    <div className="card stack" data-testid="approval">
      <strong>Approve this request ({purpose})</strong>
      <p className="subtle" style={{ margin: 0 }}>
        Nothing has been sent. It goes once to {run.provider} <code>{run.model}</code> only if you approve it. About $
        {run.estimate.cost_usd_typical.toFixed(2)}, at most ${run.estimate.cost_usd_max.toFixed(2)}. No names, calendar dates,
        accession numbers, laboratory codes, document names or record IDs are included; timing is relative. The health data
        itself is not anonymous.
      </p>
      <details>
        <summary>Data handling at this provider</summary>
        <ul>{run.data_handling.map((d) => <li key={d.setting}><strong>{d.setting}.</strong> {d.text}</li>)}</ul>
      </details>
      <details>
        <summary>Exact outgoing request (raw JSON, SHA-256 {run.payload_sha256.slice(0, 12)}...)</summary>
        <pre style={{ whiteSpace: "pre-wrap", maxHeight: 420, overflow: "auto", fontSize: 12 }}>{JSON.stringify(run.request_body, null, 1)}</pre>
      </details>
      <label className="row" style={{ color: "inherit", fontSize: 14 }}>
        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} data-testid="approve-check" />
        I approve sending exactly this request, once, to this provider and model. It does not apply to any other request.
      </label>
      <div className="row">
        <button className="primary" disabled={!ack} onClick={() => act(`/research/live-runs/${run.id}/approve`, {
          payload_sha256: run.payload_sha256, provider: run.provider, model: run.model, endpoint: run.endpoint,
          approve_this_payload_for_this_run_only: true,
        })}>Approve and send once</button>
        <button className="danger" onClick={() => act(`/research/live-runs/${run.id}/withdraw`, {})}>Withdraw</button>
      </div>
      <ErrorNote error={err} />
    </div>
  );
}

const DOMAIN_TITLE: Record<string, string> = {
  lipids: "Atherogenic lipoproteins", lpa: "Lipoprotein(a)", blood_pressure: "Blood pressure", metabolic: "Glucose and body",
  kidney: "Kidney", inflammation: "Inflammation", family_history: "Family history", exposures: "Age, sex, smoking, medications",
};

export function RetrievalSummary({ r, used }: { r: Retrieval | undefined; used?: { id: string; test: string; value: string | null; unit: string | null; date: string | null; status: string; reported_as: string }[] }) {
  if (!r) return null;
  return (
    <details className="card" data-testid="retrieval">
      <summary>
        Records used: {r.observation_ids.length} observation(s){r.period ? ` from ${r.period.first} to ${r.period.last}` : ""},{" "}
        {r.context_ids.length} self-reported item(s); domains: {r.domains.map((d) => DOMAIN_TITLE[d] ?? d).join(", ")}
      </summary>
      {r.unknown_domains.length > 0 && <p className="subtle">No information in: {r.unknown_domains.map((d) => DOMAIN_TITLE[d] ?? d).join(", ")} (unknown, not normal).</p>}
      {r.not_sent_awaiting_review > 0 && <p className="subtle">{r.not_sent_awaiting_review} row(s) awaiting review were not sent.</p>}
      {used && used.length > 0 && (
        <table>
          <thead><tr><th>Date</th><th>Test</th><th>Result</th><th>Status</th></tr></thead>
          <tbody>
            {used.map((u) => (
              <tr key={u.id}>
                <td>{u.date}</td>
                <td><Link href={`/observations/${u.id}`}>{u.test}</Link>{u.reported_as !== "current" && <span className="subtle"> (reprinted)</span>}</td>
                <td>{u.value} {u.unit}</td>
                <td><span className={`chip ${u.status === "confirmed" ? "ok" : "warn"}`}>{u.status === "confirmed" ? "confirmed" : "software-checked"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

export function NoteProposals({ run, onSaved }: { run: PartnerRun; onSaved?: () => void }) {
  const notes: { kind: string; text: string }[] = run.output?.proposed_notes ?? [];
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [err, setErr] = useState<string | null>(null);
  if (notes.length === 0) return null;
  async function keep(i: number) {
    try {
      await post("/research/notes", { kind: notes[i].kind, text: notes[i].text, source_run_id: run.id });
      setSaved(new Set(saved).add(i));
      onSaved?.();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <div>
      <p className="subtle">Proposed notes. A note is kept across sessions only if you keep it, and stays a working note, not a fact.</p>
      <ul>
        {notes.map((n, i) => (
          <li key={i}>
            <span className="chip">{n.kind.replace(/_/g, " ")}</span> {n.text}{" "}
            {saved.has(i) ? <span className="chip ok">kept</span> : <button onClick={() => keep(i)}>Keep</button>}
          </li>
        ))}
      </ul>
      <ErrorNote error={err} />
    </div>
  );
}

export { Loading, ErrorNote };

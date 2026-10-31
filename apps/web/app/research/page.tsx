"use client";

// Research priorities and investigations. Select a question; the application runs a non-identifying literature
// search, prepares one request with the relevant records and evidence, and sends it once you approve it. Every
// completed version is kept; new information shows against the latest version.

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { ErrorNote, Loading, useLoad } from "@/components/ui";
import { Approval, CheckNotice, NoteProposals, RetrievalSummary, Statements, useRun, type PartnerRun } from "@/components/Research";

interface Priority {
  id: string; title: string; question: string; relevance: string; uncertain: string; could_change: string;
  domains: string[]; evidence_ids: string[]; literature_queries: string[];
  investigation: { id: string; versions: number; latest: { summary: string | null; conclusion_status: string | null } | null } | null;
}
interface Investigation {
  id: string; priority_id: string; question: string; runs: PartnerRun[];
  new_information: { observations_added: string[]; observations_no_longer_usable: string[]; context_added: string[]; context_superseded: string[]; any: boolean } | null;
}

const CONCLUSION: Record<string, string> = {
  specific_finding_established: "A specific finding is established",
  nothing_unusual_established: "Nothing unusual is established",
  insufficient_information: "Insufficient information",
};

export default function ResearchPage() {
  const prios = useLoad(() => api<Priority[]>("/research/priorities"));
  const [inv, setInv] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [prepared, setPrepared] = useState(0); // remounts the open investigation after a new version is prepared
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("inv");
    if (q) setInv(q);
  }, []);
  async function start(priority_id: string) {
    setErr(null);
    setBusy(priority_id);
    try {
      const r = await post<{ investigation_id: string }>("/research/investigations", { priority_id });
      setInv(r.investigation_id);
      setPrepared((n) => n + 1);
      prios.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  if (prios.error) return <ErrorNote error={prios.error} />;
  if (!prios.data) return <Loading />;
  return (
    <div className="stack">
      <div>
        <h1>Research questions</h1>
        <p className="subtle">
          Up to three questions proposed from your records and what is missing from them. They are listed in order of how much
          each constrains the overall picture, which is a judgement stated in words, not a score. An unusual result is not
          a priority by itself.
        </p>
      </div>
      {prios.data.length === 0 && <div className="notice">No research question can be proposed from the current record.</div>}
      {prios.data.map((p, n) => (
        <section key={p.id} id={p.id} className="card stack" data-testid={`priority-${p.id}`}>
          <h2 style={{ margin: 0 }}>{n + 1}. {p.title}</h2>
          <p style={{ margin: 0 }}>{p.question}</p>
          <table>
            <tbody>
              <tr><th>Why it is relevant</th><td>{p.relevance}</td></tr>
              <tr><th>What is uncertain</th><td>{p.uncertain}</td></tr>
              <tr><th>What resolving it could change</th><td>{p.could_change}</td></tr>
              <tr><th>Starting evidence</th><td>{p.evidence_ids.join(", ")}; public search: {p.literature_queries.map((q) => `"${q}"`).join(", ")}</td></tr>
            </tbody>
          </table>
          <div className="row">
            {p.investigation && <button onClick={() => setInv(p.investigation!.id)}>Open investigation ({p.investigation.versions} completed version{p.investigation.versions === 1 ? "" : "s"})</button>}
            <button className="primary" disabled={busy !== null} onClick={() => start(p.id)}>
              {busy === p.id ? "Searching literature and preparing..." : p.investigation ? "Prepare a new version" : "Investigate this question"}
            </button>
            <span className="subtle">The search sends only the fixed query text above. The model request waits for your approval.</span>
          </div>
          {p.investigation?.latest?.summary && <p className="subtle">Latest: {p.investigation.latest.summary}</p>}
        </section>
      ))}
      <ErrorNote error={err} />
      {inv && <InvestigationView key={`${inv}-${prepared}`} id={inv} onChange={prios.reload} />}
    </div>
  );
}

function InvestigationView({ id, onChange }: { id: string; onChange: () => void }) {
  const { data, error, reload } = useLoad(() => api<Investigation>(`/research/investigations/${id}`), [id]);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const ni = data.new_information;
  const done = data.runs.filter((r) => r.status === "succeeded").length;
  return (
    <section className="stack" data-testid="investigation">
      <h2>Investigation: {data.question}</h2>
      {ni?.any && (
        <div className="notice warn" data-testid="new-information">
          New information since version {done}: {ni.observations_added.length} observation(s) added, {ni.context_added.length} context
          entr{ni.context_added.length === 1 ? "y" : "ies"} added, {ni.context_superseded.length + ni.observations_no_longer_usable.length} no
          longer current. Prepare a new version to update the interpretation; version {done} stays as it was.
        </div>
      )}
      {[...data.runs].reverse().map((r) => <VersionView key={r.id} initial={r} onChange={() => { reload(); onChange(); }} />)}
    </section>
  );
}

function VersionView({ initial, onChange }: { initial: PartnerRun; onChange: () => void }) {
  const { data, reload } = useRun(initial.id);
  const r = data ?? initial;
  const o = r.output;
  const search = r.context.search;
  return (
    <div className="card stack" data-testid="version">
      <div className="row">
        <strong>Version {r.context.version}</strong>
        <span className="subtle">prepared {new Date(r.created_at).toLocaleString()}</span>
        <span className="chip">{r.status.replace("_", " ")}</span>
      </div>
      <RetrievalSummary r={r.context.retrieval} />
      {search && (
        <p className="subtle">
          Literature search ({search.status}): {search.queries.map((q) => `"${q}"`).join(", ")}; {search.pmids.length} abstract(s) included as
          unverified candidates.
        </p>
      )}
      <Approval run={r} purpose="this investigation version" onChange={() => { reload(); onChange(); }} />
      {o && (
        <div className="stack" data-testid="investigation-result">
          <div className="notice"><strong>{CONCLUSION[o.conclusion_status] ?? o.conclusion_status}.</strong> {o.summary}</div>
          <CheckNotice c={r.citation_check} />
          <h3>What was learned</h3>
          <Statements items={o.learned} refs={r.refs} />
          <h3>What interpretation changed, and why</h3>
          {o.interpretation_changes.length === 0 ? <p className="subtle">No interpretation changed.</p> : (
            <ul>
              {o.interpretation_changes.map((c: { previous: string; current: string; why: never }, i: number) => (
                <li key={i}>
                  <span className="diff-old">{c.previous}</span> &rarr; {c.current}
                  <Statements items={[c.why]} refs={r.refs} />
                </li>
              ))}
            </ul>
          )}
          <h3>Contradictory or limiting evidence</h3>
          <Statements items={o.contradictory_or_limiting_evidence} refs={r.refs} />
          <h3>Does the evidence apply here?</h3>
          <Statements items={o.applicability} refs={r.refs} />
          <h3>What remains unresolved</h3>
          <Statements items={o.unresolved} refs={r.refs} />
          <h3>Information that could distinguish the explanations</h3>
          <ul>
            {o.distinguishing_information.map((d: { information: string; explanations_distinguished: string[] }, i: number) => (
              <li key={i}>{d.information} <span className="subtle">({d.explanations_distinguished.join("; ")})</span></li>
            ))}
          </ul>
          <p><Link className="button primary" href="/next">Next investigation and draft protocol</Link></p>
          <NoteProposals run={r} />
          <details><summary className="subtle">Raw response JSON</summary><pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(o, null, 1)}</pre></details>
        </div>
      )}
    </div>
  );
}

"use client";

// Next investigation: for the highest-priority question, what history can be supplied, what observations can be
// collected, and which questions need clinical review; one candidate prospective protocol; and predictions preserved
// before their outcome, with results appended later. Nothing here prescribes, orders tests or starts an experiment.

import Link from "next/link";
import { useState } from "react";
import { api, post, type Observation as ObservationOut } from "@/lib/api";
import { ErrorNote, Loading, useLoad } from "@/components/ui";
import { CheckNotice, type CitationCheck } from "@/components/Research";

interface ItemWhy { why: string; item?: string; observation?: string; question?: string }
interface NextStep { missing_history: ItemWhy[]; collectable_observations: ItemWhy[]; clinical_review_questions: ItemWhy[] }
interface Protocol {
  stage: "observation_period" | "intervention_response"; title: string; question: string; hypothesis: string; outcome: string;
  measurement_window: string; required_inputs: string[]; comparison_baseline: string; analysis_approach: string;
  counts_against_hypothesis: string; prediction: string; limitations: string[]; evidence_needed_before_intervention_prediction: string[];
  record_latest_draw_at_preservation?: string | null;
}
interface Prediction {
  id: string; status: "draft" | "locked"; protocol: Protocol; protocol_sha256: string | null; created_at: string; locked_at: string | null;
  results: { id: string; recorded_at: string; result_text: string; assessment: string; observation_ids: string[] }[];
}
interface NextView {
  priority: { id: string; title: string; question: string } | null;
  source: "investigation" | "static" | "none";
  investigation_id?: string | null; version?: number; run_id: string | null; summary?: string;
  next_step: NextStep | null; protocol: Protocol | null; protocol_blocked?: string;
  citation_check?: CitationCheck; new_information?: { any: boolean };
  predictions: Prediction[];
}

export default function NextPage() {
  const { data, error, reload } = useLoad(() => api<NextView>("/research/next"));
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  async function preserve() {
    setErr(null);
    try {
      await post("/research/predictions", { source_run_id: data!.run_id });
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  const already = data.predictions.some((p) => p.protocol.title === data.protocol?.title);
  return (
    <div className="stack">
      <div>
        <h1>Next investigation</h1>
        <p className="subtle">
          What could move the highest-priority question forward. Measurement options and protocols are drafts for you to
          consider; nothing is ordered, prescribed or started, and testing or treatment questions are marked for clinical review.
        </p>
      </div>
      {!data.priority ? <div className="notice">No research question is available yet.</div> : (
        <section className="card stack">
          <h2 style={{ margin: 0 }}>{data.priority.title}</h2>
          <p style={{ margin: 0 }}>{data.priority.question}</p>
          <p className="subtle" style={{ margin: 0 }}>
            {data.source === "investigation" ? <>From investigation version {data.version}. {data.summary}{" "}
              <Link href={`/research?inv=${data.investigation_id}`}>Open the investigation</Link></> :
              <>Default options for this question; <Link href={`/research#${data.priority.id}`}>investigate it</Link> to ground them in the evidence.</>}
          </p>
          {data.new_information?.any && <div className="notice warn">New information has arrived since this version; a new investigation version may change these options.</div>}
          {data.citation_check && <CheckNotice c={data.citation_check} />}
          {data.next_step && (
            <div className="split">
              <Bucket title="History you can supply" items={data.next_step.missing_history} k="item" link={<Link href="/context">Add it</Link>} />
              <Bucket title="Observations that could be collected" items={data.next_step.collectable_observations} k="observation" />
              <Bucket title="Questions for clinical review" items={data.next_step.clinical_review_questions} k="question" />
            </div>
          )}
        </section>
      )}

      <section className="card stack" data-testid="protocol">
        <h2 style={{ margin: 0 }}>Candidate prospective protocol</h2>
        {data.protocol ? (
          <>
            <ProtocolTable p={data.protocol} />
            <div className="row">
              <button className="primary" disabled={already} onClick={preserve}>{already ? "Preserved below" : "Preserve as a draft prediction"}</button>
              <span className="subtle">Preserving records it; locking it (below) fixes it before the outcome exists.</span>
            </div>
          </>
        ) : <p className="subtle">{data.protocol_blocked ?? "No protocol."}</p>}
        <ErrorNote error={err} />
      </section>

      <section className="stack">
        <h2>Preserved predictions</h2>
        {data.predictions.length === 0 && <p className="subtle">None yet.</p>}
        {data.predictions.map((p) => <PredictionCard key={p.id} p={p} onChange={reload} />)}
      </section>
    </div>
  );
}

function Bucket({ title, items, k, link }: { title: string; items: ItemWhy[]; k: "item" | "observation" | "question"; link?: React.ReactNode }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      {items.length === 0 ? <p className="subtle">None.</p> : (
        <ul>{items.map((i, n) => <li key={n}><strong>{i[k]}</strong> <span className="subtle">{i.why}</span></li>)}</ul>
      )}
      {link}
    </div>
  );
}

function ProtocolTable({ p }: { p: Protocol }) {
  return (
    <table className="fields">
      <tbody>
        <tr><td>Stage</td><td><span className="chip">{p.stage === "observation_period" ? "observation period" : "intervention response"}</span> {p.title}</td></tr>
        <tr><td>Question</td><td>{p.question}</td></tr>
        <tr><td>Hypothesis</td><td>{p.hypothesis}</td></tr>
        <tr><td>Outcome</td><td>{p.outcome}</td></tr>
        <tr><td>Future measurement window</td><td>{p.measurement_window}</td></tr>
        <tr><td>Required inputs</td><td>{p.required_inputs.join("; ")}</td></tr>
        <tr><td>Comparison baseline</td><td>{p.comparison_baseline}</td></tr>
        <tr><td>Analysis approach</td><td>{p.analysis_approach}</td></tr>
        <tr><td>Counts against the hypothesis</td><td>{p.counts_against_hypothesis}</td></tr>
        <tr><td>Prediction</td><td>{p.prediction}</td></tr>
        <tr><td>Limitations</td><td>{p.limitations.join("; ")}</td></tr>
        <tr><td>Needed before predicting an intervention response</td><td>{p.evidence_needed_before_intervention_prediction.join("; ")}</td></tr>
      </tbody>
    </table>
  );
}

function PredictionCard({ p, onChange }: { p: Prediction; onChange: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
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
    <div className="card stack" data-testid="prediction">
      <div className="row">
        <strong>{p.protocol.title}</strong>
        <span className={`chip ${p.status === "locked" ? "ok" : "warn"}`}>{p.status === "locked" ? `locked ${new Date(p.locked_at!).toLocaleString()}` : "draft, not locked"}</span>
        {p.protocol_sha256 && <code className="subtle">{p.protocol_sha256.slice(0, 16)}...</code>}
      </div>
      <details><summary>Protocol</summary><ProtocolTable p={p.protocol} /></details>
      {p.status === "draft" && (
        <div className="row">
          <label className="row" style={{ color: "inherit", fontSize: 14 }}>
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            Lock this prediction as it is, before its outcome. It cannot be edited afterwards.
          </label>
          <button className="primary" disabled={!ack} onClick={() => act(`/research/predictions/${p.id}/lock`, {})}>Lock</button>
        </div>
      )}
      {p.results.length > 0 && (
        <ul>{p.results.map((r) => <li key={r.id}><span className="chip">{r.assessment.replace(/_/g, " ")}</span> {r.result_text} <span className="subtle">recorded {new Date(r.recorded_at).toLocaleString()}; {r.observation_ids.length} observation(s)</span></li>)}</ul>
      )}
      {p.status === "locked" && <ResultForm p={p} onDone={onChange} />}
      <ErrorNote error={err} />
    </div>
  );
}

function ResultForm({ p, onDone }: { p: Prediction; onDone: () => void }) {
  const obs = useLoad(() => api<ObservationOut[]>("/observations"));
  const [text, setText] = useState("");
  const [assessment, setAssessment] = useState("inconclusive");
  const [picked, setPicked] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const lockDay = p.locked_at!.slice(0, 10);
  const later = (obs.data ?? []).filter((o) => o.collection_date && o.collection_date > lockDay && o.verification_status === "accepted");
  async function save() {
    setErr(null);
    try {
      await post(`/research/predictions/${p.id}/results`, { result_text: text, assessment, observation_ids: picked, context_ids: [] });
      setText("");
      setPicked([]);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <details>
      <summary>Append a result</summary>
      <div className="form-grid">
        <label>Outcome observations collected after locking
          <select multiple value={picked} onChange={(e) => setPicked(Array.from(e.target.selectedOptions).map((o) => o.value))}>
            {later.map((o) => <option key={o.id} value={o.id}>{o.collection_date} {o.original_test_name} {o.original_value} {o.original_unit}</option>)}
          </select>
          {later.length === 0 && <span className="subtle">None yet: only observations collected after {lockDay} count as outcomes.</span>}
        </label>
        <label>What was observed<textarea value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label>Against the prediction
          <select value={assessment} onChange={(e) => setAssessment(e.target.value)}>
            <option value="consistent_with_prediction">consistent with the prediction</option>
            <option value="counts_against">counts against the hypothesis</option>
            <option value="inconclusive">inconclusive</option>
          </select>
        </label>
        <button className="primary" disabled={!text.trim()} onClick={save}>Append result</button>
        <ErrorNote error={err} />
      </div>
    </details>
  );
}

"use client";

// Research conversation over the whole record. A question retrieves the relevant observations and context, shows
// what it would use, and is sent only after you approve that exact request. Kept notes carry across sessions.

import { useState } from "react";
import { api, post } from "@/lib/api";
import { ErrorNote, Loading, useLoad } from "@/components/ui";
import { Approval, CheckNotice, NoteProposals, RetrievalSummary, Statements, useRun, type PartnerRun, type Retrieval } from "@/components/Research";

interface Turn {
  message_id: string; text: string; created_at: string; retrieval: Retrieval;
  used: { id: string; test: string; value: string | null; unit: string | null; date: string | null; status: string; reported_as: string }[];
  run: PartnerRun | null;
}
interface Conversation { id: string; title: string; turns: Turn[] }
interface Note { id: string; kind: string; text: string; status: string; created_at: string }

const EXAMPLES = [
  "What does my history establish about my cardiovascular risk, and what remains unknown?",
  "Which uncertainty would most change our understanding?",
  "Are we focusing on the particle-number discrepancy because it matters, or because it happens to be unusual?",
  "What new evidence would change the current explanation?",
];

export default function AskPage() {
  const convs = useLoad(() => api<{ id: string; title: string; created_at: string }[]>("/research/conversations"));
  const notes = useLoad(() => api<Note[]>("/research/notes"));
  const [current, setCurrent] = useState<string | null>(null);
  const active = current ?? convs.data?.[0]?.id ?? null;
  return (
    <div className="stack">
      <div>
        <h1>Ask about your record</h1>
        <p className="subtle">
          Each question retrieves only the relevant observations and your health context, shows what it would use, and goes
          to the model once you approve it. Answers cite the records and sources they rest on. A proposed note becomes part of
          later questions only if you keep it; conversation history alone never turns a suggestion into a fact.
        </p>
      </div>
      <div className="row">
        <button className={!active || current === "" ? "primary" : ""} onClick={() => setCurrent("")}>New conversation</button>
        {convs.data?.map((c) => (
          <button key={c.id} className={c.id === active ? "primary" : ""} onClick={() => setCurrent(c.id)} title={c.title}>
            {c.title.length > 40 ? `${c.title.slice(0, 40)}...` : c.title}
          </button>
        ))}
      </div>
      {active && current !== "" ? (
        <ConversationView id={active} onNotes={notes.reload} />
      ) : (
        <AskBox conversationId={null} onAsked={(id) => { setCurrent(id); convs.reload(); }} />
      )}
      <KeptNotes notes={notes.data} onChange={notes.reload} />
    </div>
  );
}

function AskBox({ conversationId, onAsked }: { conversationId: string | null; onAsked: (id: string) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function ask(q: string) {
    setErr(null);
    setBusy(true);
    try {
      const r = await post<{ conversation_id: string }>("/research/questions", { text: q, conversation_id: conversationId });
      setText("");
      onAsked(r.conversation_id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card stack">
      <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask a question about your cardiovascular record" data-testid="question" />
      <div className="row">
        <button className="primary" disabled={!text.trim() || busy} onClick={() => ask(text)}>Prepare question</button>
        <span className="subtle">Preparing sends nothing; you will see the records used and the exact request first.</span>
      </div>
      {conversationId === null && (
        <div className="row">
          {EXAMPLES.map((q) => <button key={q} onClick={() => setText(q)}>{q}</button>)}
        </div>
      )}
      <ErrorNote error={err} />
    </section>
  );
}

function ConversationView({ id, onNotes }: { id: string; onNotes: () => void }) {
  const { data, error, reload } = useLoad(() => api<Conversation>(`/research/conversations/${id}`), [id]);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="stack">
      {data.turns.map((t) => <TurnView key={t.message_id} t={t} onChange={reload} onNotes={onNotes} />)}
      <AskBox conversationId={id} onAsked={() => reload()} />
    </div>
  );
}

function TurnView({ t, onChange, onNotes }: { t: Turn; onChange: () => void; onNotes: () => void }) {
  const { data: run, reload } = useRun(t.run?.id ?? null);
  const [err, setErr] = useState<string | null>(null);
  const r = run ?? t.run;
  const o = r?.output;
  async function retry() {
    try {
      await post(`/research/questions/${t.message_id}/retry`, {});
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <section className="card stack" data-testid="turn">
      <p style={{ margin: 0 }}><strong>You:</strong> {t.text}</p>
      <RetrievalSummary r={t.retrieval} used={t.used} />
      {r && <Approval run={r} purpose="answer this question" onChange={() => { reload(); onChange(); }} />}
      {r && (r.status === "withdrawn" || r.status === "failed") && <button onClick={retry}>Prepare this question again</button>}
      {o && r && (
        <div className="stack" data-testid="answer">
          <p><strong>Answer:</strong> {o.answer}</p>
          <CheckNotice c={r.citation_check} />
          <h3>Established</h3>
          <Statements items={o.established} refs={r.refs} empty="Nothing is established by confirmed records for this question." />
          <h3>Interpretations</h3>
          <Statements items={o.interpretations} refs={r.refs} />
          <h3>Unknown</h3>
          <Statements items={o.unknown} refs={r.refs} />
          <h3>What would most change the picture</h3>
          <Statements items={o.would_change_understanding} refs={r.refs} />
          <NoteProposals run={r} onSaved={onNotes} />
          <details><summary className="subtle">Raw response JSON</summary><pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(o, null, 1)}</pre></details>
        </div>
      )}
      <ErrorNote error={err} />
    </section>
  );
}

function KeptNotes({ notes, onChange }: { notes: Note[] | null; onChange: () => void }) {
  const kept = (notes ?? []).filter((n) => n.status === "accepted");
  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>Kept notes ({kept.length})</h2>
      <p className="subtle">Included in later questions and investigations as working notes, labelled as not evidence.</p>
      {kept.length === 0 ? <p className="subtle">None kept yet.</p> : (
        <ul>
          {kept.map((n) => (
            <li key={n.id}>
              <span className="chip">{n.kind.replace(/_/g, " ")}</span> {n.text}{" "}
              <button onClick={() => post(`/research/notes/${n.id}/withdraw`, {}).then(onChange)}>Withdraw</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

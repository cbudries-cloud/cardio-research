"use client";

// Self-reported health context: the history laboratory reports do not contain. Append-only; a correction
// supersedes the earlier entry and both stay visible.

import { useState } from "react";
import { api, post } from "@/lib/api";
import { ErrorNote, Loading, useLoad } from "@/components/ui";

interface Entry { id: string; domain: string; item: string; value_text: string; as_of: string | null; note: string | null; supersedes_id: string | null; created_at: string; current: boolean }
interface ContextList { items: Record<string, string[]>; entries: Entry[] }

const DOMAIN_LABEL: Record<string, string> = {
  demographics: "Age and sex", blood_pressure: "Blood pressure", family_history: "Family history", smoking: "Smoking",
  medications: "Medications and supplements", body: "Body measurements", diabetes: "Diabetes", other: "Other",
};

export default function ContextPage() {
  const { data, error, reload } = useLoad(() => api<ContextList>("/context"));
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="stack">
      <div>
        <h1>Health context</h1>
        <p className="subtle">
          Self-reported history that laboratory reports do not contain. It is kept as your report, never as a measurement,
          and stays private to this application unless you approve a request that uses it. Entries are never edited: a
          correction replaces an entry and the earlier one stays in the history.
        </p>
      </div>
      {Object.entries(data.items).map(([domain, items]) => (
        <section key={domain} className="card stack" data-testid={`context-${domain}`}>
          <h2 style={{ margin: 0 }}>{DOMAIN_LABEL[domain] ?? domain}</h2>
          {items.map((item) => (
            <ItemRow key={item} domain={domain} item={item} entries={data.entries.filter((e) => e.domain === domain && e.item === item)} onChange={reload} />
          ))}
          {domain === "other" && <ItemRow domain="other" item="" entries={data.entries.filter((e) => e.domain === "other" && !items.includes(e.item))} onChange={reload} />}
        </section>
      ))}
    </div>
  );
}

function ItemRow({ domain, item, entries, onChange }: { domain: string; item: string; entries: Entry[]; onChange: () => void }) {
  const current = entries.filter((e) => e.current);
  const history = entries.filter((e) => !e.current);
  const [open, setOpen] = useState(false);
  const [replacing, setReplacing] = useState<string | null>(null);
  const multi = domain === "blood_pressure" && item.startsWith("Blood pressure reading");
  return (
    <div>
      <div className="row">
        <strong>{item || "Other context"}</strong>
        {current.length === 0 && <span className="chip bad">unknown</span>}
        {current.map((e) => (
          <span key={e.id} className="row">
            <span className="chip ok">{e.value_text}</span>
            <span className="subtle">{e.as_of ? `as of ${e.as_of}` : "date not given"}{e.note ? `; ${e.note}` : ""}</span>
            <button onClick={() => { setReplacing(e.id); setOpen(true); }}>Correct</button>
          </span>
        ))}
        {(current.length === 0 || multi || !item) && !open && <button onClick={() => { setReplacing(null); setOpen(true); }}>{current.length ? "Add another" : "Add"}</button>}
      </div>
      {open && <EntryForm domain={domain} item={item} supersedes={replacing} onDone={() => { setOpen(false); onChange(); }} />}
      {history.length > 0 && (
        <details><summary className="subtle">{history.length} earlier entr{history.length === 1 ? "y" : "ies"}</summary>
          <ul className="subtle">{history.map((e) => <li key={e.id}>{e.value_text} ({e.as_of ?? "no date"}), entered {new Date(e.created_at).toLocaleDateString()}, superseded</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function EntryForm({ domain, item, supersedes, onDone }: { domain: string; item: string; supersedes: string | null; onDone: () => void }) {
  const [name, setName] = useState(item);
  const [value, setValue] = useState("");
  const [asOf, setAsOf] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try {
      await post("/context", { domain, item: name, value_text: value, as_of: asOf || null, note: note || null, supersedes_id: supersedes });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    }
  }
  return (
    <div className="form-grid card">
      {!item && <label>Item<input value={name} onChange={(e) => setName(e.target.value)} /></label>}
      <label>{supersedes ? "Corrected value" : "Value"}<input value={value} onChange={(e) => setValue(e.target.value)} data-testid="context-value" /></label>
      <label>As of (optional)<input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
      <label>Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <div className="row">
        <button className="primary" disabled={!value.trim() || !name.trim()} onClick={save}>Save</button>
        <button onClick={onDone}>Cancel</button>
      </div>
      <ErrorNote error={err} />
    </div>
  );
}

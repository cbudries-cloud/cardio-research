"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, type DocumentOut, type Flag, type Observation } from "@/lib/api";

interface DocumentDetail {
  document: DocumentOut;
  observations: Observation[];
  flags: Flag[];
  replaced_candidate_count: number;
  current_parser_version: string | null;
  reextract_allowed: boolean;
}
import { formatDateTime, formatValue, humanize } from "@/lib/format";
import { ErrorNote, IssueChips, Loading, StatusChip, useLoad } from "@/components/ui";
import { FlagList } from "@/components/FlagList";

const MANUAL = ["unsupported_layout", "no_text_layer", "unsupported_format", "failed"];

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, reload } = useLoad(
    () => api<DocumentDetail>(`/documents/${id}`),
    [id],
  );
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const { document: d, observations, flags } = data;
  const outdated = data.current_parser_version !== null && data.current_parser_version !== d.parser_version;

  return (
    <div className="stack">
      <div>
        <p className="subtle">
          <Link href="/documents">Records</Link> /
        </p>
        <h1>{d.original_filename}</h1>
        <div className="row">
          <StatusChip status={d.parse_status} />
          <span className="subtle">
            {d.document_format.toUpperCase()} · {(d.size_bytes / 1024).toFixed(1)} KB · uploaded{" "}
            {formatDateTime(d.uploaded_at)}
            {d.page_count ? ` · ${d.page_count} page(s)` : ""}
            {d.parser_name ? ` · parser ${d.parser_name} v${d.parser_version}` : ""}
          </span>
          <a className="button" href={`/api/v1/documents/${d.id}/original`} target="_blank" rel="noreferrer">
            Open original
          </a>
        </div>
        <p className="subtle mono">sha256 {d.sha256}</p>
        {(d.declared_date_order || d.declared_collection_method) && (
          <p className="subtle">
            Declared at upload: {d.declared_date_order && `date order ${d.declared_date_order}`}{" "}
            {d.declared_collection_method && `collection method ${d.declared_collection_method}`}
          </p>
        )}
      </div>

      {d.parse_message && (
        <div className={`notice ${MANUAL.includes(d.parse_status) ? "bad" : "warn"}`}>{d.parse_message}</div>
      )}
      {observations.some((o) => o.verification_status === "unverified") && <AutoAccept docId={d.id} onDone={reload} />}
      {data.reextract_allowed && <Reextract doc={d} outdated={outdated} current={data.current_parser_version} onDone={reload} />}
      {data.replaced_candidate_count > 0 && (
        <p className="subtle">
          {data.replaced_candidate_count} earlier candidate(s) were replaced by re-extraction. They are kept as
          rejected rows in each observation&apos;s audit history, not deleted.
        </p>
      )}
      <div className="row">
        <Link className="button" href={`/observations/new?document=${d.id}`}>
          Enter a value manually from this document
        </Link>
      </div>

      <Reconciliation docId={d.id} />

      {flags.length > 0 && (
        <>
          <h2>Review flags</h2>
          <FlagList flags={flags} onChange={reload} />
        </>
      )}

      <h2>Extracted candidates ({observations.length})</h2>
      {observations.length === 0 ? (
        <p className="subtle">No candidates were extracted from this document.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Test (as written)</th>
                <th>Value (as written)</th>
                <th>Collected</th>
                <th>Method</th>
                <th>Issues</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {observations.map((o) => (
                <tr key={o.id}>
                  <td>{o.original_test_name}</td>
                  <td>{formatValue(o.original_value, o.original_unit)}</td>
                  <td>{o.collection_date ?? <span className="subtle">{o.collection_date_raw ?? "unknown"}</span>}</td>
                  <td>{humanize(o.collection_method)}</td>
                  <td>
                    <IssueChips issues={o.extraction_issues} blocking={o.blocking_issues} />
                  </td>
                  <td>
                    <StatusChip status={o.verification_status} />
                    {o.verification_method === "automated_check" && <span className="subtle"> automated</span>}
                  </td>
                  <td>
                    <Link href={`/observations/${o.id}`}>Review</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Reextract({ doc, outdated, current, onDone }: { doc: DocumentOut; outdated: boolean; current: string | null; onDone: () => void }) {
  const [dateOrder, setDateOrder] = useState(doc.declared_date_order ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.set("date_order", dateOrder);
      await api(`/documents/${doc.id}/reextract`, { method: "POST", body: form });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={`notice ${outdated ? "warn" : ""}`}>
      <p>
        {outdated
          ? `Extracted with parser v${doc.parser_version}; the current parser is v${current}. `
          : "Nothing from this document has been reviewed yet. "}
        Re-extracting runs the current parser on the stored original and replaces the unreviewed candidates. The
        original file is unchanged and the replacement is recorded in the audit log.
      </p>
      <div className="row">
        <label>
          Numeric date order{" "}
          <select value={dateOrder} onChange={(e) => setDateOrder(e.target.value)} aria-label="Date order for re-extraction">
            <option value="">Not specified (ambiguous dates stay unresolved)</option>
            <option value="MDY">Month first (03/04/2023 = March 4)</option>
            <option value="DMY">Day first (03/04/2023 = April 3)</option>
          </select>
        </label>
        <button onClick={run} disabled={busy}>
          {busy ? "Re-extracting…" : "Re-extract with current parser"}
        </button>
      </div>
      {error && <p className="bad">{error}</p>}
    </div>
  );
}

function AutoAccept({ docId, onDone }: { docId: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    try {
      const r = await api<{ accepted: number; repeats_collapsed: number; left_for_review: number }>(
        `/documents/${docId}/auto-accept`,
        { method: "POST" },
      );
      setResult(
        `${r.accepted} accepted by automated check; ${r.repeats_collapsed} repeated printing(s) set aside; ${r.left_for_review} left for your review.`,
      );
      onDone();
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="notice">
      <p>
        Accept every candidate that passes the automated checks: no blocking issue, a number and unit found verbatim in
        its source line, and no open review flag. These are labelled &quot;accepted by automated check&quot;, not
        reviewed by you, and keep that label wherever they are used. A result printed twice in this report is counted
        once.
      </p>
      <button onClick={run} disabled={busy}>
        {busy ? "Checking…" : "Accept rows that pass automated checks"}
      </button>
      {result && <p className="subtle">{result}</p>}
    </div>
  );
}

interface Recon {
  parser: string;
  results_found: Record<string, number>;
  verification: Record<string, number>;
  set_aside: Record<string, number>;
  ambiguous_fields: Record<string, number>;
  corrections: number;
  flags: Record<string, number>;
  omitted_numeric_lines: { total: number; by_reason: Record<string, number>; lines: { page: number; reason: string; text: string }[] };
}

function Counts({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts).filter(([, n]) => n);
  return (
    <div>
      <strong>{title}</strong>
      {entries.length === 0 ? (
        <p className="subtle">none</p>
      ) : (
        <ul>
          {entries.map(([k, n]) => (
            <li key={k}>
              {humanize(k.replace(":", ", "))}: {n}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Reconciliation({ docId }: { docId: string }) {
  const { data } = useLoad(() => api<Recon>(`/documents/${docId}/reconciliation`), [docId]);
  const [open, setOpen] = useState(false);
  if (!data) return null;
  return (
    <details className="card">
      <summary>
        <strong>Source-to-extraction reconciliation</strong> ({data.parser}): {data.results_found.rows_kept} rows kept,{" "}
        {data.omitted_numeric_lines.total} numeric source lines not extracted
      </summary>
      <div className="form-grid" style={{ marginTop: 10 }}>
        <Counts title="Results found" counts={data.results_found} />
        <Counts title="Verification" counts={data.verification} />
        <Counts title="Set aside (kept, not used)" counts={data.set_aside} />
        <Counts title="Ambiguous or missing fields" counts={data.ambiguous_fields} />
        <Counts title="Review flags" counts={data.flags} />
        <Counts title="Omitted numeric lines, by reason" counts={data.omitted_numeric_lines.by_reason} />
      </div>
      <p className="subtle">Corrections recorded: {data.corrections}. Indented comment lines are counted but not listed.</p>
      <button onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} omitted lines ({data.omitted_numeric_lines.lines.length})</button>
      {open && (
        <div className="table-wrap">
          <table>
            <tbody>
              {data.omitted_numeric_lines.lines.map((l, i) => (
                <tr key={i}>
                  <td>p. {l.page}</td>
                  <td>{humanize(l.reason)}</td>
                  <td className="mono">{l.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, post, type Observation, type ObservationDetail, type Vocabulary } from "@/lib/api";
import { formatDateTime, formatValue, humanize } from "@/lib/format";
import { ErrorNote, IssueChips, Loading, StatusChip, useLoad } from "@/components/ui";
import { SourceView } from "@/components/SourceView";
import { FlagList } from "@/components/FlagList";
import { CorrectionForm } from "@/components/CorrectionForm";

export default function ObservationPage() {
  const { id } = useParams<{ id: string }>();
  const { data, error, reload } = useLoad(() => api<ObservationDetail>(`/observations/${id}`), [id]);
  const vocab = useLoad(() => api<Vocabulary>("/vocabulary"));
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const o = data.observation;

  return (
    <div className="stack">
      <div>
        <p className="subtle">
          {data.document ? <Link href={`/documents/${data.document.id}`}>{data.document.original_filename}</Link> : "No source document"} /
        </p>
        <h1>{o.original_test_name}</h1>
        <div className="row">
          <StatusChip status={o.verification_status} />
          <span className="chip">{humanize(o.extraction_status)}</span>
          <span className={`chip ${data.eligible_for_calculation_inputs ? "ok" : ""}`} data-testid="calc-eligibility">
            {data.eligible_for_calculation_inputs ? "Available to calculations" : "Not available to calculations"}
          </span>
        </div>
      </div>

      {data.superseded_by && (
        <div className="notice">
          This version was superseded. <Link href={`/observations/${data.superseded_by}`}>View the current version</Link>.
        </div>
      )}
      {o.supersedes_observation_id && (
        <div className="notice">
          {o.correction_kind === "lab_issued_correction" ? "Laboratory-issued correction" : "Participant correction"} of{" "}
          <Link href={`/observations/${o.supersedes_observation_id}`}>an earlier version</Link>
          {o.correction_reason ? `: ${o.correction_reason}` : "."}
        </div>
      )}

      {data.flags.some((f) => f.status === "open") && (
        <>
          <h2>Open flags</h2>
          <FlagList flags={data.flags.filter((f) => f.status === "open")} onChange={reload} />
        </>
      )}

      <div className="split">
        <section className="card">
          <h2 style={{ marginTop: 0 }}>Source</h2>
          <SourceView document={data.document} location={o.source_location} />
        </section>
        <section className="stack">
          <div className="card">
            <h2 style={{ marginTop: 0 }}>Extracted values</h2>
            <FieldsTable o={o} />
            <h3>Issues</h3>
            <IssueChips issues={o.extraction_issues} blocking={o.blocking_issues} />
          </div>
          <Actions detail={data} vocab={vocab.data} onChange={reload} />
        </section>
      </div>

      {data.history.length > 0 && (
        <>
          <h2>Earlier versions</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Value</th>
                  <th>Collected</th>
                  <th>Status</th>
                  <th>Recorded</th>
                </tr>
              </thead>
              <tbody>
                {data.history.map((h) => (
                  <tr key={h.id}>
                    <td>
                      <Link href={`/observations/${h.id}`}>{h.original_test_name}</Link>
                    </td>
                    <td className="diff-old">{formatValue(h.original_value, h.original_unit)}</td>
                    <td>{h.collection_date ?? h.collection_date_raw ?? "unknown"}</td>
                    <td>
                      <StatusChip status={h.verification_status} />
                    </td>
                    <td>{formatDateTime(h.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Audit trail</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Action</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {data.audit.map((a) => (
              <tr key={a.id}>
                <td>{formatDateTime(a.occurred_at)}</td>
                <td>{humanize(a.action)}</td>
                <td className="mono" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {auditSummary(a.detail)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function auditSummary(detail: Record<string, unknown>) {
  const { before, after, ...rest } = detail as { before?: Record<string, unknown>; after?: Record<string, unknown> };
  const parts = Object.entries(rest)
    .filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  if (before && after) {
    for (const k of Object.keys(after)) {
      if (JSON.stringify(before[k]) !== JSON.stringify(after[k]) && k !== "verification_status" && k !== "supersedes_observation_id" && k !== "correction_kind") {
        parts.push(`${k}: ${JSON.stringify(before[k])} -> ${JSON.stringify(after[k])}`);
      }
    }
  }
  return parts.join("\n");
}

function FieldsTable({ o }: { o: Observation }) {
  const rows: [string, React.ReactNode, React.ReactNode][] = [
    ["Test name", o.original_test_name, o.normalized_test_name ? humanize(o.normalized_test_name) : <em>not recognized</em>],
    ["Value", o.original_value ?? <em>missing</em>, o.value_numeric != null ? `${o.value_comparator ?? ""}${o.value_numeric}` : <em>not numeric</em>],
    ["Unit", o.original_unit ?? <em>missing</em>, o.normalized_unit ?? <em>unknown</em>],
    ["Value origin", "", humanize(o.value_origin)],
    ["Collection date", o.collection_date_raw ?? <em>missing</em>, o.collection_date ? `${o.collection_date} (${humanize(o.collection_date_interpretation ?? o.collection_date_status)})` : <em>{humanize(o.collection_date_status)}</em>],
    ["Report date", o.report_date_raw ?? <em>missing</em>, o.report_date ?? <em>{humanize(o.report_date_status)}</em>],
    ["Specimen", o.specimen_type_raw ?? <em>not stated</em>, `${humanize(o.specimen_type)} (${humanize(o.specimen_source)})`],
    ["Collection method", "", `${humanize(o.collection_method)} (${humanize(o.collection_method_basis)})`],
    ["Reference range", o.reference_range_raw ?? <em>none</em>, "stored separately from any decision threshold"],
    ["Laboratory flag", o.lab_flag_raw ?? "", o.lab_flag_raw ? "laboratory flag, not a diagnosis" : ""],
    ["Laboratory", o.laboratory ?? "", ""],
    ["Method", o.method ?? "", ""],
    ["Collection conditions", o.collection_conditions ?? "", ""],
    ["Result status", o.result_status_raw ?? "", o.reported_as_corrected ? "source marks result as corrected" : ""],
    ["Accession / specimen ID", o.accession_id ?? <em>not stated</em>, ""],
  ];
  const inherited = Object.entries(o.inherited_metadata ?? {});
  return (
    <table className="fields" data-testid="fields">
      <thead>
        <tr>
          <th>Field</th>
          <th>As written in source</th>
          <th>Interpreted as</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, raw, interp]) => (
          <tr key={label}>
            <td>{label}</td>
            <td>{raw}</td>
            <td>{interp}</td>
          </tr>
        ))}
      </tbody>
      {inherited.length > 0 && (
        <tfoot>
          <tr>
            <td>Inherited from report header</td>
            <td colSpan={2} data-testid="inherited">
              {inherited.map(([field, v]) => (
                <div key={field}>
                  {humanize(field)}: <span className="mono">{v.text}</span> (page {v.page})
                </div>
              ))}
            </td>
          </tr>
        </tfoot>
      )}
    </table>
  );
}

function Actions({ detail, vocab, onChange }: { detail: ObservationDetail; vocab: Vocabulary | null; onChange: () => void }) {
  const o = detail.observation;
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"none" | "correct" | "reject">("none");
  const [error, setError] = useState<string | null>(null);
  const openFlags = detail.flags.filter((f) => f.status === "open").length;

  if (o.verification_status === "rejected" || o.verification_status === "superseded") {
    return (
      <div className="card">
        <p>
          This observation is {o.verification_status}. {o.verification_note && `Reason: ${o.verification_note}`}
        </p>
      </div>
    );
  }

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      setMode("none");
      setConfirmed(false);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const canAccept = o.verification_status === "unverified" && o.blocking_issues.length === 0 && openFlags === 0;

  return (
    <div className="card stack">
      <h2 style={{ marginTop: 0 }}>Verification</h2>
      {o.verification_status === "accepted" ? (
        <p>
          {o.verification_method === "automated_check"
            ? "Accepted by automated check (not reviewed by you) "
            : "Accepted after your review "}
          {formatDateTime(o.verified_at)}
          {o.verification_note ? ` with note: ${o.verification_note}` : ""}. To change a value, record a correction; the
          accepted version is kept.
        </p>
      ) : null}
      {o.verification_status === "accepted" && o.verification_method === "automated_check" && (
        <label className="row" style={{ color: "inherit", fontSize: 14 }}>
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I compared every value above with the source and they match.
        </label>
      )}
      {o.verification_status === "accepted" ? null : (
        <>
          {o.blocking_issues.length > 0 && (
            <div className="notice bad">This candidate cannot be accepted until the blocking issues are corrected.</div>
          )}
          {openFlags > 0 && <div className="notice warn">Resolve the open flag(s) above before accepting.</div>}
          <label className="row" style={{ color: "inherit", fontSize: 14 }}>
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} disabled={!canAccept} />
            I compared every value above with the source and they match.
          </label>
          <input aria-label="Acceptance note" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} disabled={!canAccept} />
        </>
      )}
      <div className="row">
        {o.verification_status === "unverified" && (
          <button
            className="primary"
            disabled={!canAccept || !confirmed}
            onClick={() => run(() => post(`/observations/${o.id}/accept`, { confirm_source_matches: true, note: note || null }))}
          >
            Accept
          </button>
        )}
        {o.verification_status === "accepted" && o.verification_method === "automated_check" && (
          <button
            className="primary"
            disabled={!confirmed}
            onClick={() => run(() => post(`/observations/${o.id}/confirm`, { confirm_source_matches: true, note: null }))}
          >
            Confirm against source
          </button>
        )}
        <button onClick={() => setMode(mode === "correct" ? "none" : "correct")}>Correct a value</button>
        <button className="danger" onClick={() => setMode(mode === "reject" ? "none" : "reject")}>
          {o.verification_status === "accepted" ? "Withdraw" : "Reject"}
        </button>
      </div>
      {mode === "reject" && (
        <div className="row">
          <input aria-label="Reason" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ minWidth: 260 }} />
          <button className="danger" disabled={!reason.trim()} onClick={() => run(() => post(`/observations/${o.id}/reject`, { reason }))}>
            Confirm
          </button>
        </div>
      )}
      {mode === "correct" && vocab && (
        <CorrectionForm
          observation={o}
          vocab={vocab}
          onSaved={(newId) => {
            window.location.assign(`/observations/${newId}`);
          }}
        />
      )}
      <ErrorNote error={error} />
    </div>
  );
}

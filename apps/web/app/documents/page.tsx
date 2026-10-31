"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { api, type DocumentSummary } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ErrorNote, Loading, StatusChip, useLoad } from "@/components/ui";

export default function DocumentsPage() {
  const { data, error, reload } = useLoad(() => api<DocumentSummary[]>("/documents"));
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [result, setResult] = useState<DocumentSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const form = useRef<HTMLFormElement>(null);

  async function onUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setUploadError(null);
    setResult(null);
    const fd = new FormData(e.currentTarget);
    if (!(fd.get("file") as File)?.size) {
      setUploadError("Choose a file first.");
      return;
    }
    setBusy(true);
    try {
      const doc = await api<DocumentSummary>("/documents", { method: "POST", body: fd });
      setResult(doc);
      form.current?.reset();
      reload();
    } catch (err) {
      setUploadError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div>
        <h1>Records</h1>
        <p className="subtle">
          Originals are stored unchanged. Parsing creates candidates only; nothing is accepted until you review it
          against the source.
        </p>
      </div>

      <form ref={form} className="card stack" onSubmit={onUpload} aria-label="Upload document">
        <h2 style={{ marginTop: 0 }}>Upload a document</h2>
        <div className="form-grid">
          <div>
            <label htmlFor="file">CSV or text-based PDF</label>
            <input id="file" name="file" type="file" accept=".csv,.tsv,.txt,.pdf,application/pdf,text/csv" />
          </div>
          <div>
            <label htmlFor="date_order">Numeric date order in this document</label>
            <select id="date_order" name="date_order" defaultValue="">
              <option value="">Not specified (ambiguous dates stay unresolved)</option>
              <option value="MDY">Month first (03/04/2023 = March 4)</option>
              <option value="DMY">Day first (03/04/2023 = April 3)</option>
            </select>
          </div>
          <div>
            <label htmlFor="collection_method">Collection method, if the document does not say</label>
            <select id="collection_method" name="collection_method" defaultValue="">
              <option value="">Not specified</option>
              <option value="venous">Venous draw</option>
              <option value="capillary">Capillary / finger-prick</option>
            </select>
          </div>
        </div>
        <p className="subtle">
          Declarations apply only where the document itself is silent, and are recorded as declared rather than
          stated in the source.
        </p>
        <div className="row">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Uploading..." : "Upload and extract"}
          </button>
        </div>
        <ErrorNote error={uploadError} />
        {result && (
          <div className={`notice ${result.candidate_count ? "ok" : "warn"}`} role="status">
            <strong>{result.original_filename}</strong>: <StatusChip status={result.parse_status} />{" "}
            {result.candidate_count} candidate(s) extracted. {result.parse_message}{" "}
            {result.duplicate_of_document_id && "Identical file was uploaded before; duplicates are flagged. "}
            <Link href={`/documents/${result.id}`}>Open document</Link>
          </div>
        )}
      </form>

      <h2>Documents</h2>
      <ErrorNote error={error} />
      {!data ? (
        <Loading />
      ) : data.length === 0 ? (
        <p className="subtle">No documents yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Uploaded</th>
                <th>Parse status</th>
                <th>Candidates</th>
                <th>Awaiting review</th>
                <th>Accepted</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.id}>
                  <td>
                    <Link href={`/documents/${d.id}`}>{d.original_filename}</Link>{" "}
                    {d.duplicate_of_document_id && <span className="chip warn">duplicate file</span>}
                  </td>
                  <td>{formatDateTime(d.uploaded_at)}</td>
                  <td>
                    <StatusChip status={d.parse_status} />
                  </td>
                  <td>{d.candidate_count}</td>
                  <td>{d.unverified_count}</td>
                  <td>{d.accepted_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

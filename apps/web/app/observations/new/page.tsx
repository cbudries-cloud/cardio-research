"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, post, type DocumentOut, type Observation, type Vocabulary } from "@/lib/api";
import { humanize } from "@/lib/format";
import { ErrorNote, useLoad } from "@/components/ui";
import { DocumentPreview } from "@/components/SourceView";

export default function ManualEntryPage() {
  return (
    <Suspense>
      <ManualEntry />
    </Suspense>
  );
}

function ManualEntry() {
  const router = useRouter();
  const documentId = useSearchParams().get("document");
  const doc = useLoad(
    () => (documentId ? api<{ document: DocumentOut }>(`/documents/${documentId}`).then((d) => d.document) : Promise.resolve(null)),
    [documentId],
  );
  const vocab = useLoad(() => api<Vocabulary>("/vocabulary"));
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    const fd = new FormData(e.currentTarget);
    const body: Record<string, unknown> = { source_document_id: documentId };
    for (const [k, v] of fd.entries()) {
      if (typeof v === "string" && v.trim() !== "") body[k] = k === "source_page" ? Number(v) : v.trim();
    }
    try {
      const obs = await post<Observation>("/observations", body);
      router.push(`/observations/${obs.id}`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="stack">
      <div>
        <h1>Manual entry</h1>
        <p className="subtle">
          Type values exactly as they appear in the source. The entry is created as an unverified candidate and must
          be accepted like any other.
        </p>
      </div>
      <div className="split">
        <section className="card">
          <h2 style={{ marginTop: 0 }}>Source</h2>
          {documentId ? (
            doc.data ? (
              <>
                <p>
                  <Link href={`/documents/${doc.data.id}`}>{doc.data.original_filename}</Link>
                </p>
                <DocumentPreview document={doc.data} />
              </>
            ) : (
              <ErrorNote error={doc.error} />
            )
          ) : (
            <div className="notice warn">No source document selected. The entry will be marked as having no source.</div>
          )}
        </section>
        <form className="card stack" onSubmit={submit} aria-label="Manual entry">
          <div className="form-grid">
            <Text name="test_name" label="Test name (as written) *" required />
            <div>
              <label htmlFor="normalized_test_name">Recognized as</label>
              <select id="normalized_test_name" name="normalized_test_name" defaultValue="">
                <option value="">(infer from name)</option>
                {vocab.data?.normalized_test_names.map((n) => (
                  <option key={n} value={n}>
                    {humanize(n)}
                  </option>
                ))}
              </select>
            </div>
            <Text name="value" label="Value (as written) *" required />
            <Text name="unit" label="Unit (as written)" />
            <Text name="collection_date" label="Collection date" type="date" />
            <Text name="report_date" label="Report date" type="date" />
            <Text name="specimen" label="Specimen (as written)" />
            <div>
              <label htmlFor="collection_method">Collection method</label>
              <select id="collection_method" name="collection_method" defaultValue="">
                <option value="">Unknown</option>
                <option value="venous">Venous</option>
                <option value="capillary">Capillary / finger-prick</option>
              </select>
            </div>
            <Text name="reference_range" label="Reference range (as written)" />
            <Text name="flag" label="Laboratory flag (as written)" />
            <Text name="laboratory" label="Laboratory" />
            <Text name="method" label="Method" />
            <Text name="conditions" label="Collection conditions" />
            <Text name="source_page" label="Page in source" type="number" />
            <Text name="source_note" label="Where on the page" />
          </div>
          <div className="row">
            <button className="primary" type="submit">
              Create candidate
            </button>
          </div>
          <ErrorNote error={error} />
        </form>
      </div>
    </div>
  );
}

function Text({ name, label, type = "text", required }: { name: string; label: string; type?: string; required?: boolean }) {
  return (
    <div>
      <label htmlFor={name}>{label}</label>
      <input id={name} name={name} type={type} required={required} min={type === "number" ? 1 : undefined} />
    </div>
  );
}

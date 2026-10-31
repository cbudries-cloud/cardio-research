"use client";

import { useState } from "react";
import { post, type Observation, type Vocabulary } from "@/lib/api";
import { humanize } from "@/lib/format";
import { ErrorNote } from "@/components/ui";

type Field = { key: string; label: string; initial: string; type?: "date" | "select"; options?: string[] };

/** Records a correction as a new version. Only fields that differ from the current version are sent. */
export function CorrectionForm({
  observation: o,
  vocab,
  onSaved,
}: {
  observation: Observation;
  vocab: Vocabulary;
  onSaved: (newId: string) => void;
}) {
  const fields: Field[] = [
    { key: "test_name", label: "Test name (as written)", initial: o.original_test_name },
    { key: "normalized_test_name", label: "Recognized as", initial: o.normalized_test_name ?? "", type: "select", options: vocab.normalized_test_names },
    { key: "value", label: "Value (as written)", initial: o.original_value ?? "" },
    { key: "unit", label: "Unit (as written)", initial: o.original_unit ?? "" },
    { key: "collection_date", label: "Collection date", initial: o.collection_date ?? "", type: "date" },
    { key: "report_date", label: "Report date", initial: o.report_date ?? "", type: "date" },
    { key: "specimen", label: "Specimen (as written)", initial: o.specimen_type_raw ?? "" },
    { key: "specimen_type", label: "Specimen type", initial: o.specimen_type, type: "select", options: vocab.specimen_types },
    { key: "collection_method", label: "Collection method", initial: o.collection_method, type: "select", options: vocab.collection_methods },
    { key: "reference_range", label: "Reference range (as written)", initial: o.reference_range_raw ?? "" },
    { key: "flag", label: "Laboratory flag (as written)", initial: o.lab_flag_raw ?? "" },
    { key: "laboratory", label: "Laboratory", initial: o.laboratory ?? "" },
    { key: "method", label: "Method", initial: o.method ?? "" },
    { key: "conditions", label: "Collection conditions", initial: o.collection_conditions ?? "" },
    { key: "accession", label: "Accession / specimen ID", initial: o.accession_id ?? "" },
  ];
  const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(fields.map((f) => [f.key, f.initial])));
  const [kind, setKind] = useState("extraction_error");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const changed = Object.fromEntries(fields.filter((f) => values[f.key] !== f.initial && values[f.key] !== "").map((f) => [f.key, values[f.key]]));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await post<Observation>(`/observations/${o.id}/correct`, { ...changed, reason, correction_kind: kind });
      onSaved(created.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="stack" onSubmit={save} aria-label="Correction">
      <p className="subtle">
        A correction creates a new version that must be reviewed again. The current version and its values are kept.
      </p>
      <div className="form-grid">
        {fields.map((f) => (
          <div key={f.key}>
            <label htmlFor={`c-${f.key}`}>{f.label}</label>
            {f.type === "select" ? (
              <select id={`c-${f.key}`} value={values[f.key]} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                <option value="">(unchanged / unknown)</option>
                {f.options!.map((opt) => (
                  <option key={opt} value={opt}>
                    {humanize(opt)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`c-${f.key}`}
                type={f.type ?? "text"}
                value={values[f.key]}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            )}
          </div>
        ))}
        <div>
          <label htmlFor="c-kind">Kind of correction</label>
          <select id="c-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="extraction_error">Extraction error (source says something else)</option>
            <option value="lab_issued_correction">Laboratory issued a corrected result</option>
          </select>
        </div>
      </div>
      <div>
        <label htmlFor="c-reason">Reason (required)</label>
        <input id="c-reason" value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: "100%" }} />
      </div>
      <div className="row">
        <button className="primary" type="submit" disabled={!reason.trim() || Object.keys(changed).length === 0}>
          Save correction ({Object.keys(changed).length} field(s) changed)
        </button>
      </div>
      <ErrorNote error={error} />
    </form>
  );
}

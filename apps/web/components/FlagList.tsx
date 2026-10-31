"use client";

import Link from "next/link";
import { useState } from "react";
import { post, type Flag } from "@/lib/api";
import { FLAG_TEXT, MATCH_BASIS_TEXT, RESOLUTION_TEXT, humanize } from "@/lib/format";
import { ErrorNote } from "@/components/ui";

export function FlagList({ flags, onChange }: { flags: Flag[]; onChange: () => void }) {
  return (
    <div className="stack">
      {flags.map((f) => (
        <FlagCard key={f.id} flag={f} onChange={onChange} />
      ))}
    </div>
  );
}

function FlagCard({ flag, onChange }: { flag: Flag; onChange: () => void }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const open = flag.status === "open";

  async function resolve(resolution: string) {
    setError(null);
    try {
      await post(`/flags/${flag.id}/resolve`, { resolution, note: note || null });
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="card" data-flag-kind={flag.kind}>
      <div className="row">
        <span className={`chip ${open ? "warn" : ""}`}>{open ? "open" : `resolved: ${humanize(flag.resolution)}`}</span>
        <strong>{FLAG_TEXT[flag.kind] ?? humanize(flag.kind)}</strong>
        {flag.detail?.test && <span className="subtle">{humanize(flag.detail.test)}</span>}
        {flag.detail?.collection_date && <span className="subtle">collected {flag.detail.collection_date}</span>}
      </div>
      <p className="subtle">
        {flag.observation_id && (
          <>
            Newer: <Link href={`/observations/${flag.observation_id}`}>observation</Link>
          </>
        )}
        {flag.related_observation_id && (
          <>
            {" · "}Earlier: <Link href={`/observations/${flag.related_observation_id}`}>observation</Link>
          </>
        )}
        {flag.document_id && (
          <>
            {" · "}
            <Link href={`/documents/${flag.document_id}`}>document</Link>
          </>
        )}
        {flag.related_document_id && flag.related_document_id !== flag.document_id && (
          <>
            {" · "}
            <Link href={`/documents/${flag.related_document_id}`}>earlier document</Link>
          </>
        )}
      </p>
      {flag.detail?.match_basis && (
        <p className="subtle" data-testid="match-basis">
          Linked by: {MATCH_BASIS_TEXT[flag.detail.match_basis] ?? humanize(flag.detail.match_basis)}
        </p>
      )}
      {flag.resolution_note && <p className="subtle">Note: {flag.resolution_note}</p>}
      {open && (
        <div className="row">
          <input
            aria-label="Resolution note"
            placeholder="Note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{ minWidth: 220 }}
          />
          {flag.allowed_resolutions.map((r) => (
            <button key={r} onClick={() => resolve(r)}>
              {RESOLUTION_TEXT[r] ?? humanize(r)}
            </button>
          ))}
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}

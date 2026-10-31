"use client";

import { useCallback, useEffect, useState } from "react";
import { ISSUE_TEXT, humanize } from "@/lib/format";

export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    load().then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, reload };
}

const STATUS_CLASS: Record<string, string> = {
  accepted: "ok",
  unverified: "warn",
  rejected: "bad",
  superseded: "",
  parsed: "ok",
  parsed_with_issues: "warn",
  unsupported_layout: "bad",
  no_text_layer: "bad",
  unsupported_format: "bad",
  failed: "bad",
};

export function StatusChip({ status }: { status: string }) {
  return (
    <span className={`chip ${STATUS_CLASS[status] ?? ""}`} data-status={status}>
      {humanize(status)}
    </span>
  );
}

export function IssueChips({ issues, blocking }: { issues: string[]; blocking: string[] }) {
  if (!issues.length) return <span className="subtle">none</span>;
  return (
    <span className="chips">
      {issues.map((i) => (
        <span key={i} className={`chip ${blocking.includes(i) ? "bad" : "warn"}`} title={ISSUE_TEXT[i] ?? i}>
          {ISSUE_TEXT[i] ?? humanize(i)}
        </span>
      ))}
    </span>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="notice bad" role="alert">
      {error}
    </div>
  );
}

export function Loading() {
  return <p className="subtle">Loading...</p>;
}

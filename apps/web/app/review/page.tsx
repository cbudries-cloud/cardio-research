"use client";

import Link from "next/link";
import { api, type Flag, type Observation } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { ErrorNote, IssueChips, Loading, useLoad } from "@/components/ui";
import { FlagList } from "@/components/FlagList";

export default function ReviewPage() {
  const flags = useLoad(() => api<Flag[]>("/flags?status=open"));
  const queue = useLoad(() => api<Observation[]>("/observations?verification_status=unverified"));
  const reload = () => {
    flags.reload();
    queue.reload();
  };
  const rows = queue.data
    ? [...queue.data].sort((a, b) => Number(b.blocking_issues.length > 0) - Number(a.blocking_issues.length > 0))
    : null;

  return (
    <div className="stack">
      <div>
        <h1>Review queue</h1>
        <p className="subtle">
          Each candidate must be compared with its source and explicitly accepted. Blocked candidates need a
          correction first. Accepted observations involved in an open flag are withheld from calculation inputs.
        </p>
      </div>

      <h2>Open flags ({flags.data?.length ?? "..."})</h2>
      <ErrorNote error={flags.error} />
      {flags.data && (flags.data.length ? <FlagList flags={flags.data} onChange={reload} /> : <p className="subtle">No open flags.</p>)}

      <h2>Unverified candidates ({rows?.length ?? "..."})</h2>
      <ErrorNote error={queue.error} />
      {!rows ? (
        <Loading />
      ) : rows.length === 0 ? (
        <p className="subtle">Nothing awaits review.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Test (as written)</th>
                <th>Value</th>
                <th>Collected</th>
                <th>Issues</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.id}>
                  <td>{o.original_test_name}</td>
                  <td>{formatValue(o.original_value, o.original_unit)}</td>
                  <td>{o.collection_date ?? <span className="subtle">{o.collection_date_raw ?? "unknown"}</span>}</td>
                  <td>
                    <IssueChips issues={o.extraction_issues} blocking={o.blocking_issues} />
                  </td>
                  <td>
                    <Link href={`/observations/${o.id}`}>Review against source</Link>
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

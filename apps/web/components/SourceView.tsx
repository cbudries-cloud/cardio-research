"use client";

import { useState } from "react";
import type { DocumentOut, SourceLocation } from "@/lib/api";

/** Shows the passage an observation was extracted from, beside the extracted values. */
export function SourceView({ document, location }: { document: DocumentOut | null; location: SourceLocation }) {
  if (!document) {
    return <div className="notice warn">Entered without a source document. There is no source to compare against.</div>;
  }
  if ("kind" in location && location.kind === "csv_row") {
    return (
      <div className="stack" data-testid="source-csv">
        <p className="subtle">
          Row {location.row_number} of <strong>{document.original_filename}</strong>
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Column (as in file)</th>
                <th>Cell (as in file)</th>
              </tr>
            </thead>
            <tbody>
              {location.header.map((h, i) => (
                <tr key={i}>
                  <td>{h}</td>
                  <td className="mono">{location.cells[i] ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  if ("kind" in location && location.kind === "pdf_line") {
    const [x0, top, x1, bottom] = location.bbox;
    const pad = 3;
    return (
      <div className="stack" data-testid="source-pdf">
        <p className="subtle">
          Page {location.page} of <strong>{document.original_filename}</strong>. Highlighted: the line the values
          were read from.
        </p>
        <p className="mono">{location.text}</p>
        <div className="source-page">
          <img src={`/api/v1/documents/${document.id}/pages/${location.page}/image`} alt={`Page ${location.page} of source`} />
          <div
            className="hl"
            style={{
              left: `${((x0 - pad) / location.page_width) * 100}%`,
              top: `${((top - pad) / location.page_height) * 100}%`,
              width: `${((x1 - x0 + 2 * pad) / location.page_width) * 100}%`,
              height: `${((bottom - top + 2 * pad) / location.page_height) * 100}%`,
            }}
          />
        </div>
      </div>
    );
  }
  // Manual entry or a document the parser could not read.
  const page = "kind" in location && location.kind === "manual" ? location.page : null;
  return (
    <div className="stack" data-testid="source-manual">
      {"kind" in location && location.kind === "manual" && (
        <p className="subtle">
          Entered manually{page ? ` from page ${page}` : ""}
          {location.note ? `; location note: ${location.note}` : ""}.
        </p>
      )}
      <DocumentPreview document={document} initialPage={page ?? 1} />
    </div>
  );
}

export function DocumentPreview({ document, initialPage = 1 }: { document: DocumentOut; initialPage?: number }) {
  const [page, setPage] = useState(initialPage);
  if (document.document_format !== "pdf") {
    return (
      <p>
        <a href={`/api/v1/documents/${document.id}/original`} target="_blank" rel="noreferrer">
          Open the original {document.original_filename}
        </a>{" "}
        to compare.
      </p>
    );
  }
  const pages = document.page_count ?? 1;
  return (
    <div className="stack">
      {pages > 1 && (
        <div className="row">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>
            Previous page
          </button>
          <span>
            Page {page} of {pages}
          </span>
          <button onClick={() => setPage(Math.min(pages, page + 1))} disabled={page >= pages}>
            Next page
          </button>
        </div>
      )}
      <div className="source-page">
        <img src={`/api/v1/documents/${document.id}/pages/${page}/image`} alt={`Page ${page} of source`} />
      </div>
    </div>
  );
}

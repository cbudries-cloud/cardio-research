// Thin client for the FastAPI service (proxied at /api by next.config.ts).

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public info?: unknown,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Cardio-Client": "web" };
  if (init.body && !(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...headers, ...(init.headers as Record<string, string> | undefined) },
    cache: "no-store",
  });
  const body = res.headers.get("content-type")?.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : `Request failed (${res.status})`;
    throw new ApiError(res.status, message, body?.info);
  }
  return body as T;
}

export const post = <T>(path: string, data: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(data) });

export type SourceLocation =
  | { kind: "csv_row"; row_number: number; header: string[]; cells: string[] }
  | { kind: "pdf_line"; page: number; bbox: [number, number, number, number]; page_width: number; page_height: number; text: string }
  | { kind: "manual"; page: number | null; note: string | null }
  | Record<string, never>;

export interface DocumentOut {
  id: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  document_format: "csv" | "pdf" | "unsupported";
  parse_status: string;
  parse_message: string | null;
  parser_name: string | null;
  parser_version: string | null;
  page_count: number | null;
  declared_date_order: string | null;
  declared_collection_method: string | null;
  duplicate_of_document_id: string | null;
}

export interface DocumentSummary extends DocumentOut {
  candidate_count: number;
  unverified_count: number;
  accepted_count: number;
}

export interface Observation {
  id: string;
  source_document_id: string | null;
  source_location: SourceLocation;
  entry_method: string;
  original_test_name: string;
  normalized_test_name: string | null;
  original_value: string | null;
  original_unit: string | null;
  value_comparator: string | null;
  value_numeric: number | null;
  normalized_value: number | null;
  normalized_unit: string | null;
  value_origin: string;
  collection_date: string | null;
  collection_date_raw: string | null;
  collection_date_status: string;
  collection_date_interpretation: string | null;
  report_date: string | null;
  report_date_raw: string | null;
  report_date_status: string;
  specimen_type_raw: string | null;
  specimen_type: string;
  specimen_source: string;
  inherited_metadata: Record<string, { text: string; page: number }>;
  accession_id: string | null;
  collection_method: string;
  collection_method_basis: string;
  laboratory: string | null;
  method: string | null;
  reference_range_raw: string | null;
  lab_flag_raw: string | null;
  collection_conditions: string | null;
  result_status_raw: string | null;
  reported_as_corrected: boolean;
  extraction_status: string;
  extraction_issues: string[];
  blocking_issues: string[];
  verification_status: "unverified" | "accepted" | "rejected" | "superseded";
  verification_note: string | null;
  verified_at: string | null;
  verification_method: "participant_review" | "automated_check" | null;
  reported_as: "current" | "historical_in_later_report";
  supersedes_observation_id: string | null;
  correction_kind: string | null;
  correction_reason: string | null;
  created_at: string;
  created_by: string;
}

export interface Flag {
  id: string;
  kind: string;
  observation_id: string | null;
  related_observation_id: string | null;
  document_id: string | null;
  related_document_id: string | null;
  detail: Record<string, string>;
  status: string;
  resolution: string | null;
  resolution_note: string | null;
  created_at: string;
  allowed_resolutions: string[];
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  detail: Record<string, unknown>;
}

export interface ObservationDetail {
  observation: Observation;
  document: DocumentOut | null;
  flags: Flag[];
  superseded_by: string | null;
  history: Observation[];
  audit: AuditEvent[];
  eligible_for_calculation_inputs: boolean;
}

export interface Overview {
  documents: number;
  documents_needing_manual_entry: number;
  unverified: number;
  unverified_blocked: number;
  accepted: number;
  rejected: number;
  superseded: number;
  open_flags: number;
  last_activity_at: string | null;
}

export interface Vocabulary {
  normalized_test_names: string[];
  collection_methods: string[];
  specimen_types: string[];
  correction_kinds: string[];
}

export interface SeriesPoint {
  observation_id: string;
  collection_date: string;
  value: number | null;
  comparator: string | null;
  verification_status: string;
  has_open_flag: boolean;
  reference_range_raw: string | null;
  lab_flag_raw: string | null;
  laboratory: string | null;
  source_document_id: string | null;
}

export interface Series {
  collection_method: string;
  unit: string | null;
  value_origin: string;
  label: string;
  notices: string[];
  points: SeriesPoint[];
}

export interface SeriesResponse {
  key: string;
  include_unverified: boolean;
  series: Series[];
  notices: string[];
}

export interface TestEntry {
  key: string;
  label: string;
  recognized: boolean;
  accepted: number;
  unverified: number;
}

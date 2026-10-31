export const humanize = (s: string | null | undefined) => (s ? s.replace(/[_.]/g, " ") : "");

export function formatValue(value: string | null, unit: string | null) {
  if (value == null) return "(no value)";
  return unit ? `${value} ${unit}` : `${value} (no unit)`;
}

export function formatDateTime(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export const ISSUE_TEXT: Record<string, string> = {
  missing_value: "No value in source",
  non_numeric_value: "Value is not numeric",
  missing_unit: "Unit missing",
  missing_collection_date: "Collection date missing",
  ambiguous_collection_date: "Collection date ambiguous (month/day order or century unknown)",
  unparseable_collection_date: "Collection date unreadable",
  unrecognized_test_name: "Test name not recognized",
  unrecognized_unit: "Unit not recognized",
  unknown_specimen_type: "Specimen type unknown",
  unknown_collection_method: "Collection method (venous/capillary) unknown",
  missing_reference_range: "No reference range",
  missing_report_date: "No report date",
  ambiguous_report_date: "Report date ambiguous",
  unparseable_report_date: "Report date unreadable",
  value_has_comparator: "Value is a bound (e.g. <0.3), not an exact number",
  no_source_document: "Entered without a source document",
  specimen_conflict: "Specimen conflicts with this analyte (rule SPEC-1); stated value kept, not rewritten",
  specimen_inherited_from_report_header: "Specimen inherited from the report header, not stated for this row",
};

export const MATCH_BASIS_TEXT: Record<string, string> = {
  same_accession: "same accession / specimen ID (strong)",
  same_laboratory_and_date: "same laboratory and date, no shared identifier (weak)",
  date_and_test_only: "same date and test only (weak)",
};

export const FLAG_TEXT: Record<string, string> = {
  duplicate_document: "Identical file uploaded before",
  possible_duplicate: "Possible duplicate: same test, date, value and unit",
  conflicting_value: "Conflicting value: same test, date and unit, different value",
  possible_lab_correction: "Source marks this result as corrected; an earlier value exists",
};

export const RESOLUTION_TEXT: Record<string, string> = {
  acknowledged: "Acknowledge",
  distinct_measurements: "These are distinct measurements",
  reject_new: "Reject the newer one",
  new_supersedes_existing: "Newer one replaces the earlier one",
};

"""Controlled vocabularies. The migration enforces these with CHECK constraints."""

DOCUMENT_FORMATS = ("csv", "pdf", "unsupported")
PARSE_STATUSES = (
    "parsed",  # every recognized row produced a candidate
    "parsed_with_issues",  # candidates produced, some with extraction issues or skipped rows
    "unsupported_layout",  # readable text, but no layout this parser understands
    "no_text_layer",  # PDF with no extractable text (image-only / scanned)
    "unsupported_format",  # not CSV or PDF
    "failed",  # parser error; no candidates written
)
DATE_ORDERS = ("MDY", "DMY")
COLLECTION_METHODS = ("venous", "capillary", "unknown")
COLLECTION_METHOD_BASES = (
    "stated_in_source",
    "declared_at_upload",
    "participant_entered",
    "unknown",
)
SPECIMEN_SOURCES = (
    "row",  # stated for this result (CSV cell, PDF row column, or transcribed by the participant)
    "report_header",  # inherited from report-level text such as "Specimen: Serum"
    "participant_entered",  # participant chose the specimen type deliberately (audited)
    "none",  # no specimen text available
    "not_recorded",  # created before provenance was captured (migration 0002)
)
SPECIMEN_TYPES = ("serum", "plasma", "whole_blood", "dried_blood_spot", "urine", "unknown")
VALUE_ORIGINS = ("measured_direct", "calculated", "not_stated")
DATE_STATUSES = ("exact", "ambiguous", "missing", "unparseable", "participant_resolved")
ENTRY_METHODS = ("csv_parser", "pdf_parser", "manual")
EXTRACTION_STATUSES = (
    "extracted",
    "extracted_with_issues",
    "manual_entry",
    "participant_correction",
)
VERIFICATION_STATUSES = ("unverified", "accepted", "rejected", "superseded")
CORRECTION_KINDS = ("extraction_error", "lab_issued_correction")

FLAG_KINDS = (
    "duplicate_document",  # identical file bytes uploaded before
    "possible_duplicate",  # same test, date, value and unit as an existing observation
    "conflicting_value",  # same test, date and unit, different value
    "possible_lab_correction",  # source marks the result as corrected; earlier value exists
)
FLAG_RESOLUTIONS = (
    "acknowledged",
    "distinct_measurements",
    "reject_new",
    "new_supersedes_existing",
    "auto_closed",
)
ALLOWED_RESOLUTIONS = {
    "duplicate_document": ("acknowledged",),
    "possible_duplicate": ("distinct_measurements", "reject_new"),
    "conflicting_value": ("distinct_measurements", "reject_new", "new_supersedes_existing"),
    "possible_lab_correction": ("new_supersedes_existing", "distinct_measurements", "reject_new"),
}

# Extraction issues. Blocking issues prevent acceptance (and therefore prevent the
# observation from ever reaching calculation inputs) until corrected.
BLOCKING_ISSUES = frozenset(
    {
        "missing_value",
        "non_numeric_value",
        "missing_unit",
        "missing_collection_date",
        "ambiguous_collection_date",
        "unparseable_collection_date",
        "specimen_conflict",
    }
)
WARNING_ISSUES = frozenset(
    {
        "unrecognized_test_name",
        "unrecognized_unit",
        "unknown_specimen_type",
        "unknown_collection_method",
        "missing_reference_range",
        "missing_report_date",
        "ambiguous_report_date",
        "unparseable_report_date",
        "value_has_comparator",
        "no_source_document",
        "specimen_inherited_from_report_header",
        "categorical_result",
        "test_name_joined_from_wrapped_lines",
    }
)

# Rule SPEC-1 (docs/decisions.md D-024): specimen matrices that are consistent with an analyte.
# A known specimen type outside this set is a conflict, unless the participant set the specimen
# type deliberately. Deliberately small: only analytes whose matrix is unambiguous.
CONSISTENT_MATRICES = {
    "hemoglobin_a1c": frozenset({"whole_blood", "dried_blood_spot"}),
}
_BLOOD_MATRICES = frozenset({"serum", "plasma", "whole_blood", "dried_blood_spot"})
for _analyte in ("total_cholesterol", "ldl_cholesterol", "hdl_cholesterol", "triglycerides",
                 "non_hdl_cholesterol", "vldl_cholesterol", "apolipoprotein_b", "lipoprotein_a",
                 "hs_crp", "insulin"):
    CONSISTENT_MATRICES[_analyte] = _BLOOD_MATRICES

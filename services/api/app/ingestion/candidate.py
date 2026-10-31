"""Turn raw extracted text into candidate observation fields plus extraction issues.

Every entry path (CSV parser, PDF parser, manual entry, participant correction) goes
through build_candidate so that the same validation rules apply everywhere.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app import vocab
from app.ingestion import normalize
from app.ingestion.dates import parse_date


@dataclass
class RawResult:
    """Text exactly as found in the source. None means not present in the source."""

    test_name: str
    value: str | None = None
    unit: str | None = None
    collection_date: str | None = None
    report_date: str | None = None
    specimen: str | None = None
    collection_method: str | None = None
    reference_range: str | None = None
    flag: str | None = None
    laboratory: str | None = None
    method: str | None = None
    conditions: str | None = None
    result_status: str | None = None
    accession: str | None = None
    # "row" when the specimen text is stated for this result; "report_header" when inherited.
    specimen_source: str = "row"
    # Verbatim report-level text for each field this row inherited, e.g.
    # {"specimen": {"text": "Specimen: Serum", "page": 1}}.
    inherited_metadata: dict[str, Any] = field(default_factory=dict)
    source_location: dict[str, Any] = field(default_factory=dict)
    # "historical_in_later_report" for a previous result reprinted beside the current one.
    reported_as: str = "current"


@dataclass
class DocumentContext:
    declared_date_order: str | None = None
    declared_collection_method: str | None = None


@dataclass
class ResolvedOverrides:
    """Values a participant supplies directly (manual entry or correction)."""

    collection_date: date | None = None
    report_date: date | None = None
    normalized_test_name: str | None = None
    collection_method: str | None = None
    specimen_type: str | None = None
    # Provenance for specimen_type when it is carried forward from an earlier version.
    specimen_source: str | None = None


def _blank(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return s or None


def build_candidate(
    raw: RawResult, ctx: DocumentContext, overrides: ResolvedOverrides | None = None
) -> dict[str, Any]:
    ov = overrides or ResolvedOverrides()
    issues: list[str] = []

    test_name = raw.test_name.strip()
    norm_name, origin = normalize.normalize_test_name(test_name)
    origin = normalize.origin_from_method(_blank(raw.method), origin)
    if ov.normalized_test_name:
        norm_name = ov.normalized_test_name
    if norm_name is None:
        issues.append("unrecognized_test_name")

    value_raw = _blank(raw.value)
    numeric, comparator, value_issue = normalize.parse_value(value_raw)
    unit_raw = _blank(raw.unit)
    result_type = normalize.result_type(test_name, value_raw, numeric, comparator, unit_raw)
    if value_issue == "missing_value":
        issues.append(value_issue)
    elif value_issue and result_type == "text":
        issues.append(value_issue)  # free text that is neither a number nor a known category
    if result_type == "categorical":
        issues.append("categorical_result")
    if comparator:
        issues.append("value_has_comparator")  # a bound, never an exact value

    norm_unit, unit_known = normalize.normalize_unit(unit_raw)
    if unit_raw is None and result_type in ("quantity", "bounded"):
        issues.append("missing_unit")
    elif unit_raw is not None and not unit_known:
        issues.append("unrecognized_unit")
    if raw.source_location.get("name_continuation"):
        issues.append("test_name_joined_from_wrapped_lines")

    cdate = parse_date(_blank(raw.collection_date), ctx.declared_date_order)
    c_value, c_status, c_interp = cdate.value, cdate.status, cdate.interpretation
    if ov.collection_date is not None:
        c_value, c_status, c_interp = ov.collection_date, "participant_resolved", "participant_resolved"
    if c_status == "missing":
        issues.append("missing_collection_date")
    elif c_status == "ambiguous":
        issues.append("ambiguous_collection_date")
    elif c_status == "unparseable":
        issues.append("unparseable_collection_date")

    rdate = parse_date(_blank(raw.report_date), ctx.declared_date_order)
    r_value, r_status = rdate.value, rdate.status
    if ov.report_date is not None:
        r_value, r_status = ov.report_date, "participant_resolved"
    if r_status == "missing":
        issues.append("missing_report_date")
    elif r_status == "ambiguous":
        issues.append("ambiguous_report_date")
    elif r_status == "unparseable":
        issues.append("unparseable_report_date")

    specimen_raw = _blank(raw.specimen)
    specimen_type, method_from_specimen = normalize.normalize_specimen(specimen_raw)
    specimen_source = raw.specimen_source if specimen_raw else "none"
    if ov.specimen_type:
        specimen_type = ov.specimen_type
        specimen_source = ov.specimen_source or "participant_entered"
    if specimen_type == "unknown":
        issues.append("unknown_specimen_type")
    if specimen_source == "report_header":
        issues.append("specimen_inherited_from_report_header")
    if specimen_conflict(norm_name, specimen_type, specimen_source):
        issues.append("specimen_conflict")

    stated_method = normalize.normalize_collection_method(_blank(raw.collection_method)) or method_from_specimen
    if ov.collection_method and ov.collection_method != "unknown":
        coll_method, coll_basis = ov.collection_method, "participant_entered"
    elif stated_method:
        coll_method, coll_basis = stated_method, "stated_in_source"
    elif ctx.declared_collection_method and ctx.declared_collection_method != "unknown":
        coll_method, coll_basis = ctx.declared_collection_method, "declared_at_upload"
    else:
        coll_method, coll_basis = "unknown", "unknown"
    if coll_method == "unknown":
        issues.append("unknown_collection_method")

    range_raw = _blank(raw.reference_range)
    low, high = normalize.parse_reference_range(range_raw)
    if range_raw is None:
        issues.append("missing_reference_range")

    status_raw = _blank(raw.result_status)

    return {
        "original_test_name": test_name,
        "normalized_test_name": norm_name,
        "original_value": value_raw,
        "original_unit": unit_raw,
        "value_comparator": comparator,
        "value_numeric": numeric,
        "normalized_value": numeric,  # no unit conversion (decision D-011)
        "normalized_unit": norm_unit,
        "value_origin": origin,
        "collection_date": c_value,
        "collection_date_raw": _blank(raw.collection_date),
        "collection_date_status": c_status,
        "collection_date_interpretation": c_interp,
        "report_date": r_value,
        "report_date_raw": _blank(raw.report_date),
        "report_date_status": r_status,
        "specimen_type_raw": specimen_raw,
        "specimen_type": specimen_type,
        "specimen_source": specimen_source,
        "inherited_metadata": raw.inherited_metadata,
        "accession_id": _blank(raw.accession),
        "collection_method": coll_method,
        "collection_method_basis": coll_basis,
        "laboratory": _blank(raw.laboratory),
        "method": _blank(raw.method),
        "reference_range_raw": range_raw,
        "reference_range_low": low,
        "reference_range_high": high,
        "lab_flag_raw": _blank(raw.flag),
        "collection_conditions": _blank(raw.conditions),
        "result_status_raw": status_raw,
        "reported_as_corrected": normalize.is_corrected_status(status_raw),
        "source_location": raw.source_location,
        "reported_as": raw.reported_as,
        "result_type": result_type,
        "extraction_issues": issues,
    }


def specimen_conflict(normalized_test_name: str | None, specimen_type: str, specimen_source: str) -> bool:
    """Rule SPEC-1 (D-024). A known specimen type that is inconsistent with the analyte is a
    conflict. The stated value is kept as-is; nothing is rewritten to the expected matrix.
    A deliberate participant choice is exempt (it is audited instead)."""
    if specimen_type == "unknown" or specimen_source == "participant_entered" or not normalized_test_name:
        return False
    allowed = vocab.CONSISTENT_MATRICES.get(normalized_test_name)
    return allowed is not None and specimen_type not in allowed


def blocking_issues(issues: list[str]) -> list[str]:
    return [i for i in issues if i in vocab.BLOCKING_ISSUES]


def as_float(d: Decimal | None) -> float | None:
    return float(d) if d is not None else None

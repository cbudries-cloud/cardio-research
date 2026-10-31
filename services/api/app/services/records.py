"""Verified-record workflow: import -> extract -> validate -> human verification -> accepted.

All state changes write an audit event in the same transaction. Observation values are
never edited in place (the database refuses it); corrections create a superseding row.
"""

import collections
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import vocab
from app.ingestion import csv_parser, pdf_parser
from app.ingestion.candidate import DocumentContext, RawResult, ResolvedOverrides, blocking_issues, build_candidate
from app.models import AuditEvent, Observation, ReviewFlag, SourceDocument
from app.storage import DocumentStorage, sha256_hex

ACTOR = "participant"  # single local participant; no accounts in this build (decision D-004)


class DomainError(Exception):
    def __init__(self, status_code: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


SNAPSHOT_FIELDS = (
    "original_test_name", "normalized_test_name", "original_value", "original_unit", "value_comparator",
    "value_numeric", "normalized_unit", "value_origin", "collection_date", "collection_date_raw",
    "collection_date_status", "report_date", "report_date_raw", "specimen_type_raw", "specimen_type", "specimen_source", "accession_id",
    "collection_method", "collection_method_basis", "laboratory", "method", "reference_range_raw",
    "lab_flag_raw", "collection_conditions", "result_status_raw", "extraction_issues",
    "verification_status", "supersedes_observation_id", "correction_kind",
)


def snapshot(obs: Observation) -> dict[str, Any]:
    return {f: _json_safe(getattr(obs, f)) for f in SNAPSHOT_FIELDS}


def audit(session: Session, participant_id, action: str, entity_type: str, entity_id, detail: dict) -> None:
    session.add(
        AuditEvent(
            participant_id=participant_id,
            actor=ACTOR,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail={k: _json_safe(v) for k, v in detail.items()},
        )
    )


# --- Import -------------------------------------------------------------------


def detect_format(filename: str, data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return "pdf"
    lower = filename.lower()
    if lower.endswith((".csv", ".tsv", ".txt")):
        try:
            data[:4096].decode("utf-8")
            return "csv"
        except UnicodeDecodeError:
            return "unsupported"
    return "unsupported"


def import_document(
    session: Session,
    storage: DocumentStorage,
    participant_id: uuid.UUID,
    filename: str,
    content_type: str | None,
    data: bytes,
    declared_date_order: str | None,
    declared_collection_method: str | None,
) -> SourceDocument:
    doc_id = uuid.uuid4()
    fmt = detect_format(filename, data)
    digest = sha256_hex(data)
    storage_key = f"{participant_id}/{doc_id}"

    prior = session.scalars(
        select(SourceDocument)
        .where(SourceDocument.participant_id == participant_id, SourceDocument.sha256 == digest)
        .order_by(SourceDocument.uploaded_at)
    ).first()

    status, message, results, pages, parser = _run_parser(fmt, data)

    doc = SourceDocument(
        id=doc_id,
        participant_id=participant_id,
        original_filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest,
        storage_key=storage_key,
        document_format=fmt,
        parse_status=status,
        parse_message=message,
        parser_name=parser[0],
        parser_version=parser[1],
        page_count=pages,
        declared_date_order=declared_date_order,
        declared_collection_method=declared_collection_method,
        duplicate_of_document_id=prior.id if prior else None,
    )
    session.add(doc)
    session.flush()
    audit(session, participant_id, "document.imported", "source_document", doc_id,
          {"format": fmt, "parse_status": status, "candidates": len(results), "sha256": digest})

    if prior:
        session.add(ReviewFlag(
            participant_id=participant_id, kind="duplicate_document", document_id=doc_id,
            related_document_id=prior.id,
            detail={"reason": "Identical file contents were uploaded previously."},
        ))

    _create_candidates(session, doc, results)

    # Write the file last; if storage fails the transaction is rolled back by the caller.
    storage.put(storage_key, data)
    return doc


def _run_parser(fmt: str, data: bytes):
    """Return (status, message, results, page_count, (parser_name, parser_version))."""
    if fmt == "csv":
        parsed = csv_parser.parse_csv(data)
        return parsed.status, parsed.message, parsed.results, None, (csv_parser.PARSER_NAME, csv_parser.PARSER_VERSION)
    if fmt == "pdf":
        p = pdf_parser.parse_pdf(data)
        return p.status, p.message, p.results, p.page_count, (pdf_parser.PARSER_NAME, pdf_parser.PARSER_VERSION)
    return (
        "unsupported_format",
        "Only CSV and text-based PDF files are parsed. The original is stored; enter values manually.",
        [], None, (None, None),
    )


def _create_candidates(session: Session, doc: SourceDocument, results) -> None:
    ctx = DocumentContext(doc.declared_date_order, doc.declared_collection_method)
    entry_method = "csv_parser" if doc.document_format == "csv" else "pdf_parser"
    any_issue = False
    for raw in results:
        fields = build_candidate(raw, ctx)
        blocked = bool(blocking_issues(fields["extraction_issues"]))
        any_issue = any_issue or blocked
        create_observation(
            session, doc.participant_id, fields, entry_method=entry_method, source_document_id=doc.id,
            extraction_status="extracted_with_issues" if blocked else "extracted",
        )
    if doc.parse_status == "parsed" and any_issue:
        doc.parse_status = "parsed_with_issues"


REEXTRACTION_NOTE = "Replaced by re-extraction of the stored original"


def current_parser_version(fmt: str) -> str | None:
    return {"csv": csv_parser.PARSER_VERSION, "pdf": pdf_parser.PARSER_VERSION}.get(fmt)


def _automated_only(o: Observation) -> bool:
    return o.verification_status == "accepted" and o.verification_method == "automated_check"


def reextract_allowed(observations) -> bool:
    """Allowed until a person has reviewed or corrected something. Automated acceptances are
    not a person's work; re-extraction withdraws them (audited) and they can be re-run."""
    return not any(
        (o.verification_status not in ("unverified", "rejected") and not _automated_only(o))
        or o.supersedes_observation_id
        for o in observations)


def reextract_document(
    session: Session, storage: DocumentStorage, doc_id: uuid.UUID, declared_date_order: str | None,
) -> SourceDocument:
    """Re-run the current parser on a stored original.

    Allowed only while no candidate from the document has been accepted, corrected or used
    as a correction base. Earlier candidates are rejected with an audited reason (never
    deleted); the original file is unchanged.
    """
    doc = session.get(SourceDocument, doc_id)
    if doc is None:
        raise DomainError(404, "Document not found.")
    existing = session.scalars(select(Observation).where(Observation.source_document_id == doc.id)).all()
    if doc.document_format not in ("csv", "pdf"):
        raise DomainError(409, "This file format is not parsed.")
    if not reextract_allowed(existing):
        raise DomainError(409, "A candidate from this document has already been reviewed or corrected. "
                               "Re-extraction is only possible before review.")
    previous = {"parser_version": doc.parser_version, "parse_status": doc.parse_status,
                "declared_date_order": doc.declared_date_order}
    reason = f"{REEXTRACTION_NOTE} (parser {doc.parser_name} v{doc.parser_version} replaced)."
    for o in existing:
        if o.verification_status == "unverified" or _automated_only(o):
            reject(session, o.id, reason)
    status, message, results, pages, parser = _run_parser(doc.document_format, storage.get(doc.storage_key))
    if declared_date_order is not None:
        doc.declared_date_order = declared_date_order or None
    doc.parse_status, doc.parse_message, doc.page_count = status, message, pages
    doc.parser_name, doc.parser_version = parser
    session.flush()
    _create_candidates(session, doc, results)
    audit(session, doc.participant_id, "document.reextracted", "source_document", doc.id,
          {"previous": previous, "parser_version": doc.parser_version, "parse_status": doc.parse_status,
           "declared_date_order": doc.declared_date_order, "candidates": len(results),
           "rejected_previous_candidates": sum(1 for o in existing if o.verification_note == reason)})
    return doc


# --- Observation creation and duplicate detection ------------------------------


def create_observation(
    session: Session,
    participant_id: uuid.UUID,
    fields: dict[str, Any],
    *,
    entry_method: str,
    source_document_id: uuid.UUID | None,
    extraction_status: str,
    supersedes: Observation | None = None,
    correction_kind: str | None = None,
    correction_reason: str | None = None,
) -> Observation:
    obs = Observation(
        id=uuid.uuid4(),
        participant_id=participant_id,
        source_document_id=source_document_id,
        entry_method=entry_method,
        extraction_status=extraction_status,
        verification_status="unverified",
        supersedes_observation_id=supersedes.id if supersedes else None,
        correction_kind=correction_kind,
        correction_reason=correction_reason,
        created_by="system" if entry_method in ("csv_parser", "pdf_parser") and not supersedes else ACTOR,
        **fields,
    )
    session.add(obs)
    session.flush()
    _detect_duplicates(session, obs, exclude={supersedes.id} if supersedes else set())
    return obs


def _detect_duplicates(session: Session, obs: Observation, exclude: set[uuid.UUID]) -> None:
    if obs.collection_date is None:
        return
    name_match = (
        Observation.normalized_test_name == obs.normalized_test_name
        if obs.normalized_test_name
        else Observation.original_test_name.ilike(obs.original_test_name)
    )
    existing = session.scalars(
        select(Observation).where(
            Observation.participant_id == obs.participant_id,
            Observation.id != obs.id,
            Observation.verification_status.in_(("unverified", "accepted")),
            Observation.collection_date == obs.collection_date,
            name_match,
        )
    ).all()
    for other in existing:
        if other.id in exclude or other.normalized_unit != obs.normalized_unit:
            continue
        if (
            obs.collection_method != "unknown"
            and other.collection_method != "unknown"
            and obs.collection_method != other.collection_method
        ):
            continue  # distinct streams (e.g. capillary vs venous) are not duplicates
        basis = collection_event_match(obs, other)
        same_value = (other.value_numeric == obs.value_numeric and other.value_comparator == obs.value_comparator
                      and (obs.value_numeric is not None or other.original_value == obs.original_value))
        if basis == "different_collection_event":
            if not (same_value and obs.source_document_id and obs.source_document_id == other.source_document_id):
                continue  # same day, different accession: a legitimate repeat test, not a duplicate
            # One document, two accession identifiers, identical result: most likely the same result printed in
            # two sections of the report. Flagged (never merged) so it cannot be counted twice silently.
            basis = "same_document_different_accession"
        if same_value:
            kind = "possible_duplicate"
        elif obs.reported_as_corrected:
            kind = "possible_lab_correction"
        else:
            kind = "conflicting_value"
        session.add(ReviewFlag(
            participant_id=obs.participant_id, kind=kind, observation_id=obs.id,
            related_observation_id=other.id, document_id=obs.source_document_id,
            related_document_id=other.source_document_id,
            detail={"test": obs.normalized_test_name or obs.original_test_name,
                    "collection_date": obs.collection_date.isoformat(),
                    "match_basis": basis,
                    "accession_new": obs.accession_id, "accession_existing": other.accession_id,
                    "laboratory_new": obs.laboratory, "laboratory_existing": other.laboratory},
        ))
    session.flush()


def collection_event_match(a: Observation, b: Observation) -> str:
    """How strongly two same-test, same-date observations are known to share a collection event.

    - same_accession: both state the same accession/specimen identifier (strong).
    - different_collection_event: both state identifiers and they differ (not compared further).
    - same_laboratory_and_date: no shared identifier; laboratory labels match (weak).
    - date_and_test_only: nothing beyond date and test links them (weakest).
    Weak matches still only raise a review flag; nothing is merged automatically.
    """
    if a.accession_id and b.accession_id:
        same = a.accession_id.strip().lower() == b.accession_id.strip().lower()
        return "same_accession" if same else "different_collection_event"
    if a.laboratory and b.laboratory and a.laboratory.strip().lower() == b.laboratory.strip().lower():
        return "same_laboratory_and_date"
    return "date_and_test_only"


def open_flags_for(session: Session, obs_id: uuid.UUID) -> list[ReviewFlag]:
    return list(session.scalars(
        select(ReviewFlag).where(
            ReviewFlag.status == "open",
            or_(ReviewFlag.observation_id == obs_id, ReviewFlag.related_observation_id == obs_id),
        )
    ).all())


def _auto_close_flags(session: Session, obs_id: uuid.UUID, why: str) -> None:
    for flag in open_flags_for(session, obs_id):
        flag.status = "resolved"
        flag.resolution = "auto_closed"
        flag.resolution_note = why
        flag.resolved_at = _now()
        audit(session, flag.participant_id, "flag.auto_closed", "review_flag", flag.id, {"reason": why})


# --- Verification ------------------------------------------------------------


def get_observation(session: Session, obs_id: uuid.UUID) -> Observation:
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise DomainError(404, "Observation not found.")
    return obs


def accept(session: Session, obs_id: uuid.UUID, confirm_source_matches: bool, note: str | None) -> Observation:
    obs = get_observation(session, obs_id)
    if obs.verification_status != "unverified":
        raise DomainError(409, f"Only unverified observations can be accepted (status: {obs.verification_status}).")
    if not confirm_source_matches:
        raise DomainError(422, "Acceptance requires confirming that the values match the source.")
    blocking = blocking_issues(obs.extraction_issues)
    if blocking:
        raise DomainError(409, "Resolve blocking extraction issues with a correction before accepting.",
                          {"blocking_issues": blocking})
    flags = open_flags_for(session, obs.id)
    if flags:
        raise DomainError(409, "Resolve open review flags before accepting.",
                          {"open_flags": [str(f.id) for f in flags]})
    obs.verification_status = "accepted"
    obs.verified_at = _now()
    obs.verification_note = note
    obs.verification_method = "participant_review"
    audit(session, obs.participant_id, "observation.accepted", "observation", obs.id,
          {"note": note, "warnings": [i for i in obs.extraction_issues if i in vocab.WARNING_ISSUES]})
    return obs


def confirm_automated(session: Session, obs_id: uuid.UUID, confirm_source_matches: bool, note: str | None) -> Observation:
    obs = get_observation(session, obs_id)
    if obs.verification_status != "accepted" or obs.verification_method != "automated_check":
        raise DomainError(409, "Only observations accepted by automated check can be confirmed.")
    if not confirm_source_matches:
        raise DomainError(422, "Confirmation requires confirming that the values match the source.")
    obs.verification_method = "participant_review"
    obs.verification_note = note or "Confirmed against the source by the participant (previously accepted by automated check)."
    audit(session, obs.participant_id, "observation.confirmed", "observation", obs.id,
          {"previous_method": "automated_check", "note": note})
    return obs


# --- Automated acceptance --------------------------------------------------------

AUTO_ACCEPT_NOTE = (
    "Accepted by automated check, not reviewed by the participant: no blocking extraction issue, "
    "value (and unit, where the result type needs one) found verbatim in the source line, no open review flag."
)
REPEAT_IN_REPORT_NOTE = "Same result printed twice in this report (automated check)."
REPEAT_TWO_ACCESSIONS_NOTE = ("Same result printed twice in this report (automated check); the two printings carry different "
                              "accession identifiers. Whether they are one specimen needs participant verification.")
CORROBORATION_NOTE = "Reprinted previous result that matches the original report's result (corroboration; automated check)."


def automated_check_failures(session: Session, obs: Observation) -> list[str]:
    """Reasons an unverified observation may not be accepted automatically (empty = passes)."""
    failures = []
    if blocking_issues(obs.extraction_issues):
        failures.append("blocking_issue")
    if obs.result_type == "text":
        failures.append("free_text_result")
    elif obs.result_type != "categorical" and obs.value_numeric is None:
        failures.append("not_numeric")
    loc = obs.source_location or {}
    tokens = loc.get("text", "").split() if loc.get("kind") == "pdf_line" else [c.strip() for c in loc.get("cells", [])]
    if not tokens:
        failures.append("no_source_line")
    else:
        if not obs.original_value or obs.original_value.split()[0] not in tokens:
            failures.append("value_not_in_source_line")
        unit_required = obs.result_type in ("quantity", "bounded")
        if (unit_required or obs.original_unit) and (not obs.original_unit or obs.original_unit not in tokens):
            failures.append("unit_not_in_source_line")
    if open_flags_for(session, obs.id):
        failures.append("open_flag")
    return failures


def auto_accept_document(session: Session, doc_id: uuid.UUID) -> dict[str, Any]:
    """Collapse results printed twice in the same report, then accept every remaining
    candidate that passes the automated checks, labelled verification_method='automated_check'.
    Anything that fails a check stays unverified for participant review."""
    doc = session.get(SourceDocument, doc_id)
    if doc is None:
        raise DomainError(404, "Document not found.")
    candidates = session.scalars(
        select(Observation).where(Observation.source_document_id == doc_id, Observation.verification_status == "unverified")
        .order_by(Observation.created_at, Observation.id)
    ).all()
    ids = {o.id for o in candidates}
    repeats = 0
    for flag in session.scalars(select(ReviewFlag).where(
        ReviewFlag.status == "open", ReviewFlag.kind == "possible_duplicate",
        ReviewFlag.observation_id.in_(ids), ReviewFlag.related_observation_id.in_(ids),
    )).all():
        new, existing = get_observation(session, flag.observation_id), get_observation(session, flag.related_observation_id)
        same = (new.original_value, new.original_unit, new.collection_date, new.normalized_test_name) == (
            existing.original_value, existing.original_unit, existing.collection_date, existing.normalized_test_name)
        if same and flag.status == "open" and new.verification_status == "unverified":
            note = (REPEAT_TWO_ACCESSIONS_NOTE if (flag.detail or {}).get("match_basis") == "same_document_different_accession"
                    else REPEAT_IN_REPORT_NOTE)
            resolve_flag(session, flag.id, "reject_new", note)
            repeats += 1
    # A previous result reprinted by a later report that matches the original report's own
    # result corroborates it: keep the original, set the reprint aside with a note.
    corroborated = 0
    for flag in session.scalars(select(ReviewFlag).where(
        ReviewFlag.status == "open", ReviewFlag.kind == "possible_duplicate",
        or_(ReviewFlag.observation_id.in_(ids), ReviewFlag.related_observation_id.in_(ids)),
    )).all():
        a, b = get_observation(session, flag.observation_id), get_observation(session, flag.related_observation_id)
        pair = {a.reported_as: a, b.reported_as: b}
        if set(pair) != {"current", "historical_in_later_report"}:
            continue
        hist, orig = pair["historical_in_later_report"], pair["current"]
        same = (hist.value_numeric, hist.normalized_unit, hist.collection_date) == (
            orig.value_numeric, orig.normalized_unit, orig.collection_date) and hist.value_numeric is not None
        if same and hist.verification_status == "unverified":
            reject(session, hist.id, f"{CORROBORATION_NOTE} Original observation {orig.id}.")
            corroborated += 1
    accepted, kept = 0, collections.Counter()
    for obs in candidates:
        if obs.verification_status != "unverified":
            continue
        failures = automated_check_failures(session, obs)
        if failures:
            kept.update(failures)
            continue
        obs.verification_status = "accepted"
        obs.verified_at = _now()
        obs.verification_note = AUTO_ACCEPT_NOTE
        obs.verification_method = "automated_check"
        audit(session, obs.participant_id, "observation.accepted", "observation", obs.id,
              {"method": "automated_check", "warnings": [i for i in obs.extraction_issues if i in vocab.WARNING_ISSUES]})
        accepted += 1
    result = {"repeats_collapsed": repeats, "reprints_corroborating": corroborated, "accepted": accepted,
              "left_for_review": sum(1 for o in candidates if o.verification_status == "unverified"),
              "reasons_left": dict(kept)}
    audit(session, doc.participant_id, "document.auto_accepted", "source_document", doc.id, result)
    session.flush()
    return result


def reject(session: Session, obs_id: uuid.UUID, reason: str) -> Observation:
    obs = get_observation(session, obs_id)
    if obs.verification_status not in ("unverified", "accepted"):
        raise DomainError(409, f"Observation is {obs.verification_status} and cannot be rejected.")
    if not reason.strip():
        raise DomainError(422, "A reason is required.")
    previous = obs.verification_status
    obs.verification_status = "rejected"
    obs.verification_note = reason
    audit(session, obs.participant_id,
          "observation.withdrawn" if previous == "accepted" else "observation.rejected",
          "observation", obs.id, {"reason": reason, "previous_status": previous})
    _auto_close_flags(session, obs.id, "observation rejected")
    return obs


CORRECTABLE_TEXT_FIELDS = (
    "test_name", "value", "unit", "specimen", "reference_range", "flag", "laboratory", "method", "conditions",
    "accession",
)


def _participant_basis(method: str) -> str:
    return "participant_entered" if method != "unknown" else "unknown"


def _set_collection_method(fields: dict[str, Any], method: str, basis: str) -> None:
    fields["collection_method"] = method
    fields["collection_method_basis"] = basis
    issues = [i for i in fields["extraction_issues"] if i != "unknown_collection_method"]
    if method == "unknown":
        issues.append("unknown_collection_method")
    fields["extraction_issues"] = issues


def _raw_from_observation(obs: Observation) -> RawResult:
    return RawResult(
        test_name=obs.original_test_name,
        value=obs.original_value,
        unit=obs.original_unit,
        collection_date=obs.collection_date_raw,
        report_date=obs.report_date_raw,
        specimen=obs.specimen_type_raw,
        collection_method=None,
        reference_range=obs.reference_range_raw,
        flag=obs.lab_flag_raw,
        laboratory=obs.laboratory,
        method=obs.method,
        conditions=obs.collection_conditions,
        result_status=obs.result_status_raw,
        accession=obs.accession_id,
        specimen_source=obs.specimen_source if obs.specimen_source in ("row", "report_header") else "row",
        inherited_metadata=obs.inherited_metadata,
        source_location=obs.source_location,
        reported_as=obs.reported_as,
    )


def _context_for(session: Session, document_id: uuid.UUID | None) -> DocumentContext:
    if document_id is None:
        return DocumentContext()
    doc = session.get(SourceDocument, document_id)
    if doc is None:
        raise DomainError(404, "Source document not found.")
    return DocumentContext(doc.declared_date_order, doc.declared_collection_method)


def correct(
    session: Session,
    obs_id: uuid.UUID,
    changes: dict[str, Any],
    reason: str,
    correction_kind: str,
) -> Observation:
    old = get_observation(session, obs_id)
    if old.verification_status not in ("unverified", "accepted"):
        raise DomainError(409, f"Observation is {old.verification_status}; correct its current version instead.")
    if correction_kind not in vocab.CORRECTION_KINDS:
        raise DomainError(422, "Unknown correction kind.")
    if not reason.strip():
        raise DomainError(422, "A reason is required for every correction.")

    raw = _raw_from_observation(old)
    for key in CORRECTABLE_TEXT_FIELDS:
        if key in changes and changes[key] is not None:
            setattr(raw, key, changes[key])
    # Interpretations the participant already supplied carry forward unless this correction
    # changes them or the text they were derived from.
    overrides = ResolvedOverrides(
        collection_date=changes.get("collection_date")
        or (old.collection_date if old.collection_date_status == "participant_resolved" else None),
        report_date=changes.get("report_date")
        or (old.report_date if old.report_date_status == "participant_resolved" else None),
        normalized_test_name=changes.get("normalized_test_name")
        or (old.normalized_test_name if "test_name" not in changes else None),
        specimen_type=changes.get("specimen_type")
        or (old.specimen_type if "specimen" not in changes and old.specimen_source == "participant_entered" else None),
    )
    if "specimen" in changes:
        # The participant states the specimen text applies to this result.
        raw.specimen_source = "row"
        raw.inherited_metadata = {k: v for k, v in raw.inherited_metadata.items() if k != "specimen"}
    fields = build_candidate(raw, _context_for(session, old.source_document_id), overrides)

    # Collection method is not re-derived from text on correction: keep the old value
    # and its basis unless the participant changes it.
    method_change = changes.get("collection_method")
    if method_change is None:
        _set_collection_method(fields, old.collection_method, old.collection_method_basis)
    elif method_change in vocab.COLLECTION_METHODS:
        _set_collection_method(fields, method_change, _participant_basis(method_change))
    else:
        raise DomainError(422, "Unknown collection method.")
    if old.source_document_id is None:
        fields["extraction_issues"].append("no_source_document")

    old.verification_status = "superseded"
    _auto_close_flags(session, old.id, "observation superseded by correction")
    new = create_observation(
        session, old.participant_id, fields, entry_method=old.entry_method,
        source_document_id=old.source_document_id, extraction_status="participant_correction",
        supersedes=old, correction_kind=correction_kind, correction_reason=reason,
    )
    audit(session, old.participant_id, "observation.corrected", "observation", old.id,
          {"reason": reason, "correction_kind": correction_kind, "new_observation_id": new.id,
           "before": snapshot(old), "after": snapshot(new)})
    audit(session, old.participant_id, "observation.created_by_correction", "observation", new.id,
          {"supersedes": old.id, "reason": reason})
    return new


def create_manual(
    session: Session,
    participant_id: uuid.UUID,
    raw: RawResult,
    overrides: ResolvedOverrides,
    source_document_id: uuid.UUID | None,
) -> Observation:
    fields = build_candidate(raw, _context_for(session, source_document_id), overrides)
    if overrides.collection_method in vocab.COLLECTION_METHODS:
        _set_collection_method(fields, overrides.collection_method, _participant_basis(overrides.collection_method))
    if source_document_id is None:
        fields["extraction_issues"].append("no_source_document")
    obs = create_observation(
        session, participant_id, fields, entry_method="manual",
        source_document_id=source_document_id, extraction_status="manual_entry",
    )
    audit(session, participant_id, "observation.manually_entered", "observation", obs.id,
          {"source_document_id": source_document_id})
    return obs


# --- Review flags --------------------------------------------------------------


def resolve_flag(session: Session, flag_id: uuid.UUID, resolution: str, note: str | None) -> ReviewFlag:
    flag = session.get(ReviewFlag, flag_id)
    if flag is None:
        raise DomainError(404, "Flag not found.")
    if flag.status != "open":
        raise DomainError(409, "Flag is already resolved.")
    if resolution not in vocab.ALLOWED_RESOLUTIONS[flag.kind]:
        raise DomainError(422, f"Resolution '{resolution}' is not valid for a {flag.kind} flag.",
                          {"allowed": list(vocab.ALLOWED_RESOLUTIONS[flag.kind])})

    flag.status = "resolved"
    flag.resolution = resolution
    flag.resolution_note = note
    flag.resolved_at = _now()
    audit(session, flag.participant_id, "flag.resolved", "review_flag", flag.id,
          {"kind": flag.kind, "resolution": resolution, "note": note})

    if resolution == "reject_new":
        reject(session, flag.observation_id, note or f"Rejected while resolving {flag.kind} flag.")
    elif resolution == "new_supersedes_existing":
        new = get_observation(session, flag.observation_id)
        existing = get_observation(session, flag.related_observation_id)
        if new.supersedes_observation_id is not None:
            raise DomainError(409, "The new observation already supersedes another observation.")
        if existing.verification_status not in ("unverified", "accepted"):
            raise DomainError(409, f"The existing observation is {existing.verification_status}.")
        new.supersedes_observation_id = existing.id
        if new.correction_kind is None:
            new.correction_kind = "lab_issued_correction"
        existing.verification_status = "superseded"
        audit(session, flag.participant_id, "observation.superseded_by_lab_correction", "observation",
              existing.id, {"new_observation_id": new.id, "flag_id": flag.id})
        _auto_close_flags(session, existing.id, "observation superseded by lab-issued correction")
    session.flush()
    return flag

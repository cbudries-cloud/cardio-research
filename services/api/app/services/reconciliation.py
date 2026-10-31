"""Source-to-extraction reconciliation for one document.

Re-reads the stored original with the current parser to list lines that contain a number but
produced no result, and summarises what happened to every extracted row. Nothing is written.
"""

import collections
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import vocab
from app.ingestion import pdf_parser
from app.models import Observation, ReviewFlag, SourceDocument
from app.services import records
from app.storage import DocumentStorage

AMBIGUITY_ISSUES = (
    "ambiguous_collection_date", "unparseable_collection_date", "missing_collection_date",
    "unknown_specimen_type", "unrecognized_test_name", "unrecognized_unit", "missing_unit",
    "missing_reference_range", "non_numeric_value", "specimen_conflict",
)


def _rejection_category(note: str | None) -> str:
    note = note or ""
    if note.startswith(records.REEXTRACTION_NOTE):
        return "replaced_by_reextraction"
    if note.startswith(records.REPEAT_TWO_ACCESSIONS_NOTE):
        return "same_result_two_accessions_in_report"
    if note.startswith(records.REPEAT_IN_REPORT_NOTE):
        return "same_result_printed_twice_in_report"
    if note.startswith(records.CORROBORATION_NOTE):
        return "reprint_corroborating_original_report"
    if note.startswith("Superseded by a later upload"):
        return "superseded_upload"
    return "rejected_by_participant"


def reconcile(session: Session, storage: DocumentStorage, doc_id: uuid.UUID) -> dict[str, Any]:
    doc = session.get(SourceDocument, doc_id)
    if doc is None:
        raise records.DomainError(404, "Document not found.")
    obs = session.scalars(select(Observation).where(Observation.source_document_id == doc_id)).all()
    live = [o for o in obs if o.verification_status != "rejected"]
    rejected = collections.Counter(_rejection_category(o.verification_note) for o in obs if o.verification_status == "rejected")

    omitted: list[dict] = []
    if doc.document_format == "pdf":
        pdf_parser.parse_pdf(storage.get(doc.storage_key), skipped=omitted)
    omitted_by_reason = collections.Counter(o["reason"] for o in omitted)

    ids = {o.id for o in obs}
    flags = session.scalars(select(ReviewFlag).where(
        (ReviewFlag.observation_id.in_(ids)) | (ReviewFlag.related_observation_id.in_(ids))
        | (ReviewFlag.document_id == doc_id))).all()

    return {
        "document_id": str(doc.id),
        "parser": f"{doc.parser_name} v{doc.parser_version}",
        "current_parser_version": records.current_parser_version(doc.document_format),
        "results_found": {
            "rows_kept": len(live),
            "current": sum(o.reported_as == "current" for o in live),
            "historical_in_later_report": sum(o.reported_as == "historical_in_later_report" for o in live),
            "recognized_test_name": sum(o.normalized_test_name is not None for o in live),
            "unfamiliar_test_name_kept": sum(o.normalized_test_name is None for o in live),
        },
        "verification": {
            "accepted_participant_review": sum(o.verification_status == "accepted" and o.verification_method == "participant_review" for o in live),
            "accepted_automated_check_not_confirmed": sum(o.verification_status == "accepted" and o.verification_method == "automated_check" for o in live),
            "unverified": sum(o.verification_status == "unverified" for o in live),
            "unverified_blocked": sum(o.verification_status == "unverified" and bool(records.blocking_issues(o.extraction_issues)) for o in live),
            "superseded": sum(o.verification_status == "superseded" for o in live),
        },
        "set_aside": dict(rejected),
        "ambiguous_fields": {k: v for k, v in collections.Counter(
            i for o in live for i in o.extraction_issues if i in AMBIGUITY_ISSUES).most_common()},
        "accession_identifiers_in_document": len({o.accession_id for o in obs if o.accession_id and not
                                                  (o.verification_note or "").startswith(records.REEXTRACTION_NOTE)}),
        "corrections": sum(o.supersedes_observation_id is not None for o in obs),
        "flags": {f"{kind}:{status}": n for (kind, status), n in collections.Counter((f.kind, f.status) for f in flags).items()},
        "omitted_numeric_lines": {"total": len(omitted), "by_reason": dict(omitted_by_reason),
                                  "lines": [o for o in omitted if o["reason"] != "indented_comment"]},
        "blocking_issue_codes": sorted(vocab.BLOCKING_ISSUES),
    }

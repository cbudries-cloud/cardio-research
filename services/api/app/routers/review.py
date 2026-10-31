import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calc_inputs import calculation_input_observations
from app.db import get_session
from app.deps import get_participant_id
from app import vocab
from app.ingestion.candidate import blocking_issues
from app.ingestion.normalize import TEST_ALIASES
from app.models import AuditEvent, Observation, ReviewFlag, SourceDocument
from app.routers.common import flag_out
from app.schemas import CalculationInput, FlagOut, Overview, ResolveFlagIn
from app.services import records, series

router = APIRouter(tags=["review"])

MANUAL_ENTRY_STATUSES = ("unsupported_layout", "no_text_layer", "unsupported_format", "failed")


@router.get("/overview", response_model=Overview)
def overview(session: Session = Depends(get_session), participant_id=Depends(get_participant_id)):
    by_status = dict(session.execute(
        select(Observation.verification_status, func.count())
        .where(Observation.participant_id == participant_id).group_by(Observation.verification_status)
    ).all())
    unverified = session.scalars(
        select(Observation).where(Observation.participant_id == participant_id,
                                  Observation.verification_status == "unverified")
    ).all()
    docs = session.execute(
        select(func.count(), func.count().filter(SourceDocument.parse_status.in_(MANUAL_ENTRY_STATUSES)))
        .where(SourceDocument.participant_id == participant_id)
    ).one()
    return Overview(
        documents=docs[0],
        documents_needing_manual_entry=docs[1],
        unverified=by_status.get("unverified", 0),
        unverified_blocked=sum(1 for o in unverified if blocking_issues(o.extraction_issues)),
        accepted=by_status.get("accepted", 0),
        rejected=by_status.get("rejected", 0),
        superseded=by_status.get("superseded", 0),
        open_flags=session.scalar(select(func.count()).select_from(ReviewFlag).where(
            ReviewFlag.participant_id == participant_id, ReviewFlag.status == "open")) or 0,
        last_activity_at=session.scalar(select(func.max(AuditEvent.occurred_at)).where(
            AuditEvent.participant_id == participant_id)),
    )


@router.get("/flags", response_model=list[FlagOut])
def list_flags(status: str = "open", session: Session = Depends(get_session),
               participant_id=Depends(get_participant_id)):
    rows = session.scalars(
        select(ReviewFlag).where(ReviewFlag.participant_id == participant_id, ReviewFlag.status == status)
        .order_by(ReviewFlag.created_at, ReviewFlag.id)
    ).all()
    return [flag_out(f) for f in rows]


@router.post("/flags/{flag_id}/resolve", response_model=FlagOut)
def resolve_flag(flag_id: uuid.UUID, body: ResolveFlagIn, session: Session = Depends(get_session)):
    flag = records.resolve_flag(session, flag_id, body.resolution, body.note)
    session.commit()
    return flag_out(flag)


@router.get("/series")
def list_series(session: Session = Depends(get_session), participant_id=Depends(get_participant_id)):
    return series.list_tests(session, participant_id)


@router.get("/series/{key}")
def get_series(key: str, include_unverified: bool = False, session: Session = Depends(get_session),
               participant_id=Depends(get_participant_id)):
    return series.build_series(session, participant_id, key, include_unverified)


@router.get("/calculation-inputs/observations", response_model=list[CalculationInput])
def calculation_inputs(normalized_test_name: str | None = None, session: Session = Depends(get_session),
                       participant_id=Depends(get_participant_id)):
    """The only interface future calculations may use. Returns accepted observations only."""
    return [
        CalculationInput(
            observation_id=o.id, normalized_test_name=o.normalized_test_name,
            value=float(o.value_numeric) if o.value_numeric is not None else None,
            comparator=o.value_comparator, result_type=o.result_type, value_as_written=o.original_value,
            unit=o.normalized_unit, value_origin=o.value_origin,
            collection_date=o.collection_date, collection_method=o.collection_method,
            specimen_type=o.specimen_type, specimen_source=o.specimen_source, laboratory=o.laboratory,
            accession_id=o.accession_id, source_document_id=o.source_document_id,
            verified_at=o.verified_at,
            verification_method=o.verification_method,
        )
        for o in calculation_input_observations(session, participant_id, normalized_test_name)
    ]


@router.get("/vocabulary")
def vocabulary():
    return {
        "normalized_test_names": sorted(TEST_ALIASES),
        "collection_methods": list(vocab.COLLECTION_METHODS),
        "specimen_types": list(vocab.SPECIMEN_TYPES),
        "correction_kinds": list(vocab.CORRECTION_KINDS),
        "blocking_issues": sorted(vocab.BLOCKING_ISSUES),
    }

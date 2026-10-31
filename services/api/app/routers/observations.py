import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calc_inputs import is_calculation_input
from app.db import get_session
from app.deps import get_participant_id
from app.ingestion.candidate import RawResult, ResolvedOverrides
from app.models import AuditEvent, Observation, ReviewFlag, SourceDocument
from app.routers.common import flag_out, observation_out
from app.schemas import (
    AcceptIn, AuditOut, CorrectIn, DocumentOut, ManualIn, ObservationDetail, ObservationOut, RejectIn,
)
from app.services import records

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=list[ObservationOut])
def list_observations(
    verification_status: str | None = None,
    document_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    participant_id=Depends(get_participant_id),
):
    stmt = select(Observation).where(Observation.participant_id == participant_id)
    if verification_status:
        stmt = stmt.where(Observation.verification_status == verification_status)
    if document_id:
        stmt = stmt.where(Observation.source_document_id == document_id)
    rows = session.scalars(stmt.order_by(Observation.collection_date.desc().nulls_first(),
                                         Observation.created_at, Observation.id)).all()
    return [observation_out(o) for o in rows]


@router.get("/{obs_id}", response_model=ObservationDetail)
def get_observation(obs_id: uuid.UUID, session: Session = Depends(get_session)):
    obs = records.get_observation(session, obs_id)
    doc = session.get(SourceDocument, obs.source_document_id) if obs.source_document_id else None
    flags = session.scalars(
        select(ReviewFlag).where(or_(ReviewFlag.observation_id == obs.id,
                                     ReviewFlag.related_observation_id == obs.id))
        .order_by(ReviewFlag.created_at, ReviewFlag.id)
    ).all()
    successor = session.scalars(
        select(Observation.id).where(Observation.supersedes_observation_id == obs.id)
    ).first()
    history = []
    cursor = obs
    while cursor.supersedes_observation_id:
        cursor = session.get(Observation, cursor.supersedes_observation_id)
        history.append(observation_out(cursor))
    chain_ids = [obs.id] + [h.id for h in history]
    if obs.source_document_id:
        chain_ids.append(obs.source_document_id)  # include the import event for provenance
    audit = session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id.in_(chain_ids)).order_by(AuditEvent.id.desc())
    ).all()
    return ObservationDetail(
        observation=observation_out(obs),
        document=DocumentOut.model_validate(doc) if doc else None,
        flags=[flag_out(f) for f in flags],
        superseded_by=successor,
        history=history,
        audit=[AuditOut.model_validate(a) for a in audit],
        eligible_for_calculation_inputs=is_calculation_input(session, obs.id),
    )


@router.post("", response_model=ObservationOut, status_code=201)
def create_manual(body: ManualIn, session: Session = Depends(get_session),
                  participant_id=Depends(get_participant_id)):
    location = {"kind": "manual", "page": body.source_page, "note": body.source_note}
    raw = RawResult(
        test_name=body.test_name, value=body.value, unit=body.unit,
        collection_date=body.collection_date_text, report_date=None, specimen=body.specimen,
        reference_range=body.reference_range, flag=body.flag, laboratory=body.laboratory,
        method=body.method, conditions=body.conditions, accession=body.accession, source_location=location,
    )
    overrides = ResolvedOverrides(
        collection_date=body.collection_date, report_date=body.report_date,
        normalized_test_name=body.normalized_test_name, collection_method=body.collection_method,
        specimen_type=body.specimen_type,
    )
    obs = records.create_manual(session, participant_id, raw, overrides, body.source_document_id)
    session.commit()
    return observation_out(obs)


@router.post("/{obs_id}/accept", response_model=ObservationOut)
def accept(obs_id: uuid.UUID, body: AcceptIn, session: Session = Depends(get_session)):
    obs = records.accept(session, obs_id, body.confirm_source_matches, body.note)
    session.commit()
    return observation_out(obs)


@router.post("/{obs_id}/confirm", response_model=ObservationOut)
def confirm(obs_id: uuid.UUID, body: AcceptIn, session: Session = Depends(get_session)):
    """Participant confirms an automated-check acceptance against the source."""
    obs = records.confirm_automated(session, obs_id, body.confirm_source_matches, body.note)
    session.commit()
    return observation_out(obs)


@router.post("/{obs_id}/reject", response_model=ObservationOut)
def reject(obs_id: uuid.UUID, body: RejectIn, session: Session = Depends(get_session)):
    obs = records.reject(session, obs_id, body.reason)
    session.commit()
    return observation_out(obs)


@router.post("/{obs_id}/correct", response_model=ObservationOut, status_code=201)
def correct(obs_id: uuid.UUID, body: CorrectIn, session: Session = Depends(get_session)):
    changes = body.model_dump(exclude={"reason", "correction_kind"}, exclude_none=True)
    if not changes:
        raise HTTPException(422, "A correction must change at least one field.")
    obs = records.correct(session, obs_id, changes, body.reason, body.correction_kind)
    session.commit()
    return observation_out(obs)

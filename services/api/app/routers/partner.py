"""Research partner endpoints: overview, priorities, self-reported context, questions, notes,
investigations, the next-investigation view and preserved predictions. Live runs prepared here are
approved through /research/live-runs/{id}/approve like every other run (D-050)."""

import hashlib
import json
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_participant_id
from app.models import (Observation, ParticipantContext, ResearchConversation, ResearchInvestigation, ResearchLiveRun,
                        ResearchNote, ResearchPrediction, ResearchPredictionResult)
from app.research import partner
from app.services import records
from app.services.records import DomainError

router = APIRouter(prefix="/research", tags=["research-partner"])
context_router = APIRouter(prefix="/context", tags=["context"])

Participant = Depends(get_participant_id)
Db = Depends(get_session)


def _run_full(session: Session, run: ResearchLiveRun) -> dict:
    return {**partner.run_view(run, session), "refs": partner.resolve_refs(session, run)}


def _own_run(session: Session, run_id: uuid.UUID, participant_id: uuid.UUID) -> ResearchLiveRun:
    run = session.get(ResearchLiveRun, run_id)
    if run is None or run.participant_id != participant_id:
        raise HTTPException(404, "Run not found.")
    return run


# --- Overview and priorities ----------------------------------------------------------

@router.get("/overview")
def get_overview(session: Session = Db, participant_id: uuid.UUID = Participant):
    return partner.overview(session, participant_id)


@router.get("/priorities")
def get_priorities(session: Session = Db, participant_id: uuid.UUID = Participant):
    invs = {i["priority_id"]: i for i in partner.investigation_summaries(session, participant_id)}
    return [{**p, "investigation": invs.get(p["id"])} for p in partner.priorities(session, participant_id)]


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, session: Session = Db, participant_id: uuid.UUID = Participant):
    return _run_full(session, _own_run(session, run_id, participant_id))


# --- Self-reported context ------------------------------------------------------------

class ContextIn(BaseModel):
    domain: str
    item: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=2000)
    as_of: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    supersedes_id: uuid.UUID | None = None


@context_router.get("")
def list_context(session: Session = Db, participant_id: uuid.UUID = Participant):
    rows = session.scalars(select(ParticipantContext).where(ParticipantContext.participant_id == participant_id)
                           .order_by(ParticipantContext.created_at)).all()
    current = {c["context_id"] for c in partner.current_context(session, participant_id)}
    return {"items": partner.CONTEXT_ITEMS,
            "entries": [{"id": str(r.id), "domain": r.domain, "item": r.item, "value_text": r.value_text,
                         "as_of": r.as_of.isoformat() if r.as_of else None, "note": r.note,
                         "supersedes_id": str(r.supersedes_id) if r.supersedes_id else None,
                         "created_at": r.created_at.isoformat(), "current": str(r.id) in current} for r in rows]}


@context_router.post("", status_code=201)
def add_context(body: ContextIn, session: Session = Db, participant_id: uuid.UUID = Participant):
    if body.domain not in partner.CONTEXT_ITEMS:
        raise DomainError(422, "Unknown context domain.")
    if body.as_of and body.as_of > date.today():
        raise DomainError(422, "The date cannot be in the future.")
    if body.supersedes_id:
        old = session.get(ParticipantContext, body.supersedes_id)
        if old is None or old.participant_id != participant_id:
            raise DomainError(404, "The entry to supersede was not found.")
        if body.supersedes_id not in {uuid.UUID(c["context_id"]) for c in partner.current_context(session, participant_id)}:
            raise DomainError(409, "That entry is already superseded.")
    row = ParticipantContext(id=uuid.uuid4(), participant_id=participant_id, domain=body.domain, item=body.item.strip(),
                             value_text=body.value_text.strip(), as_of=body.as_of, note=body.note, supersedes_id=body.supersedes_id)
    session.add(row)
    records.audit(session, participant_id, "context.entered", "participant_context", row.id,
                  {"domain": body.domain, "supersedes": bool(body.supersedes_id)})
    session.commit()
    return {"id": str(row.id)}


# --- Questions ------------------------------------------------------------------------

class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None


@router.post("/questions", status_code=201)
def ask(body: QuestionIn, session: Session = Db, participant_id: uuid.UUID = Participant):
    conv, msg, run = partner.ask(session, participant_id, body.conversation_id, body.text)
    session.commit()
    return {"conversation_id": str(conv.id), "message_id": str(msg.id), "run": _run_full(session, run)}


@router.get("/conversations")
def list_conversations(session: Session = Db, participant_id: uuid.UUID = Participant):
    rows = session.scalars(select(ResearchConversation).where(ResearchConversation.participant_id == participant_id)
                           .order_by(ResearchConversation.created_at.desc())).all()
    return [{"id": str(c.id), "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, session: Session = Db, participant_id: uuid.UUID = Participant):
    conv = session.get(ResearchConversation, conversation_id)
    if conv is None or conv.participant_id != participant_id:
        raise HTTPException(404, "Conversation not found.")
    turns = []
    for m, run in partner.conversation_turns(session, conv.id):
        turns.append({"message_id": str(m.id), "text": m.text, "created_at": m.created_at.isoformat(),
                      "retrieval": m.retrieval, "used": _used(session, m.retrieval),
                      "run": _run_full(session, run) if run else None})
    return {"id": str(conv.id), "title": conv.title, "turns": turns}


def _used(session: Session, retrieval: dict) -> list[dict]:
    """The observations a question used, for the private page."""
    ids = [uuid.UUID(i) for i in retrieval.get("observation_ids", [])]
    if not ids:
        return []
    rows = session.scalars(select(Observation).where(Observation.id.in_(ids))).all()
    out = [{"id": str(o.id), "test": o.original_test_name, "value": o.original_value, "unit": o.normalized_unit or o.original_unit,
            "date": o.collection_date.isoformat() if o.collection_date else None,
            "status": "confirmed" if o.verification_method == "participant_review" else "software_checked",
            "reported_as": o.reported_as} for o in rows]
    return sorted(out, key=lambda r: (r["date"] or "", r["test"]))


@router.post("/questions/{message_id}/retry", status_code=201)
def retry_question(message_id: uuid.UUID, session: Session = Db, participant_id: uuid.UUID = Participant):
    """Prepare a new request for an earlier question (after a withdrawn or failed run). Asked as a new turn."""
    from app.models import ResearchMessage

    msg = session.get(ResearchMessage, message_id)
    if msg is None or msg.participant_id != participant_id:
        raise HTTPException(404, "Question not found.")
    conv, new_msg, run = partner.ask(session, participant_id, msg.conversation_id, msg.text)
    session.commit()
    return {"conversation_id": str(conv.id), "message_id": str(new_msg.id), "run": _run_full(session, run)}


# --- Notes (explicitly accepted memory) ------------------------------------------------

class NoteIn(BaseModel):
    kind: str
    text: str = Field(min_length=1, max_length=2000)
    source_run_id: uuid.UUID | None = None


def _note(n: ResearchNote) -> dict:
    return {"id": str(n.id), "kind": n.kind, "text": n.text, "status": n.status,
            "source_run_id": str(n.source_run_id) if n.source_run_id else None, "created_at": n.created_at.isoformat(),
            "withdrawn_at": n.withdrawn_at.isoformat() if n.withdrawn_at else None}


@router.get("/notes")
def list_notes(session: Session = Db, participant_id: uuid.UUID = Participant):
    return [_note(n) for n in session.scalars(select(ResearchNote).where(ResearchNote.participant_id == participant_id)
                                              .order_by(ResearchNote.created_at)).all()]


@router.post("/notes", status_code=201)
def accept_note(body: NoteIn, session: Session = Db, participant_id: uuid.UUID = Participant):
    if body.kind not in ("working_hypothesis", "open_question", "context_note"):
        raise DomainError(422, "Unknown note kind.")
    if body.source_run_id:
        _own_run(session, body.source_run_id, participant_id)
    n = ResearchNote(id=uuid.uuid4(), participant_id=participant_id, kind=body.kind, text=body.text.strip(),
                     status="accepted", source_run_id=body.source_run_id)
    session.add(n)
    records.audit(session, participant_id, "research.note_accepted", "research_note", n.id, {"kind": body.kind})
    session.commit()
    return _note(n)


@router.post("/notes/{note_id}/withdraw")
def withdraw_note(note_id: uuid.UUID, session: Session = Db, participant_id: uuid.UUID = Participant):
    n = session.get(ResearchNote, note_id)
    if n is None or n.participant_id != participant_id:
        raise HTTPException(404, "Note not found.")
    if n.status != "accepted":
        raise DomainError(409, "This note is already withdrawn.")
    n.status, n.withdrawn_at = "withdrawn", datetime.now(timezone.utc)
    records.audit(session, participant_id, "research.note_withdrawn", "research_note", n.id, {})
    session.commit()
    return _note(n)


# --- Investigations -------------------------------------------------------------------

class InvestigationIn(BaseModel):
    priority_id: str


@router.get("/investigations")
def list_investigations(session: Session = Db, participant_id: uuid.UUID = Participant):
    return partner.investigation_summaries(session, participant_id)


@router.post("/investigations", status_code=201)
def start_investigation(body: InvestigationIn, session: Session = Db, participant_id: uuid.UUID = Participant):
    inv, run = partner.start_investigation(session, participant_id, body.priority_id)
    session.commit()
    return {"investigation_id": str(inv.id), "run": _run_full(session, run)}


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: uuid.UUID, session: Session = Db, participant_id: uuid.UUID = Participant):
    inv = session.get(ResearchInvestigation, inv_id)
    if inv is None or inv.participant_id != participant_id:
        raise HTTPException(404, "Investigation not found.")
    runs = partner.investigation_runs(session, inv.id)
    done = [r for r in runs if r.status == "succeeded"]
    return {"id": str(inv.id), "priority_id": inv.priority_id, "question": inv.question,
            "runs": [_run_full(session, r) for r in runs],
            "new_information": partner.new_information(session, participant_id, done[-1]) if done else None}


# --- Next investigation and predictions -------------------------------------------------

def _pred(session: Session, p: ResearchPrediction) -> dict:
    results = session.scalars(select(ResearchPredictionResult).where(ResearchPredictionResult.prediction_id == p.id)
                              .order_by(ResearchPredictionResult.recorded_at)).all()
    return {"id": str(p.id), "status": p.status, "protocol": p.protocol, "protocol_sha256": p.protocol_sha256,
            "investigation_id": str(p.investigation_id) if p.investigation_id else None,
            "source_run_id": str(p.source_run_id) if p.source_run_id else None,
            "created_at": p.created_at.isoformat(), "locked_at": p.locked_at.isoformat() if p.locked_at else None,
            "results": [{"id": str(r.id), "recorded_at": r.recorded_at.isoformat(), "result_text": r.result_text,
                         "assessment": r.assessment, "observation_ids": r.observation_ids, "context_ids": r.context_ids}
                        for r in results]}


@router.get("/next")
def next_investigation(session: Session = Db, participant_id: uuid.UUID = Participant):
    return partner.next_view(session, participant_id) | {
        "predictions": [_pred(session, p) for p in session.scalars(select(ResearchPrediction).where(
            ResearchPrediction.participant_id == participant_id).order_by(ResearchPrediction.created_at.desc())).all()]}


class PredictionIn(BaseModel):
    source_run_id: uuid.UUID


@router.post("/predictions", status_code=201)
def preserve_prediction(body: PredictionIn, session: Session = Db, participant_id: uuid.UUID = Participant):
    run = _own_run(session, body.source_run_id, participant_id)
    if run.kind != "investigation" or run.status != "succeeded" or not (run.output or {}).get("protocol"):
        raise DomainError(409, "Only a completed investigation's protocol can be preserved.")
    protocol = {**run.output["protocol"], "record_latest_draw_at_preservation": _latest_draw(session, participant_id)}
    p = ResearchPrediction(id=uuid.uuid4(), participant_id=participant_id,
                           investigation_id=uuid.UUID(run.context["investigation_id"]), source_run_id=run.id,
                           protocol=protocol, status="draft")
    session.add(p)
    records.audit(session, participant_id, "research.prediction_drafted", "research_prediction", p.id, {})
    session.commit()
    return _pred(session, p)


def _latest_draw(session: Session, participant_id: uuid.UUID) -> str | None:
    rows = partner.record_rows(session, participant_id)
    dates = [r["collection_date"] for r in rows if r["collection_date"]]
    return max(dates) if dates else None


def _own_pred(session: Session, pid: uuid.UUID, participant_id: uuid.UUID) -> ResearchPrediction:
    p = session.get(ResearchPrediction, pid)
    if p is None or p.participant_id != participant_id:
        raise HTTPException(404, "Prediction not found.")
    return p


@router.post("/predictions/{pid}/lock")
def lock_prediction(pid: uuid.UUID, session: Session = Db, participant_id: uuid.UUID = Participant):
    p = _own_pred(session, pid, participant_id)
    if p.status != "draft":
        raise DomainError(409, "This prediction is already locked.")
    p.status = "locked"
    p.protocol_sha256 = hashlib.sha256(json.dumps(p.protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    p.locked_at = datetime.now(timezone.utc)
    records.audit(session, participant_id, "research.prediction_locked", "research_prediction", p.id,
                  {"protocol_sha256": p.protocol_sha256})
    session.commit()
    return _pred(session, p)


class ResultIn(BaseModel):
    result_text: str = Field(min_length=1, max_length=4000)
    assessment: str
    observation_ids: list[uuid.UUID] = []
    context_ids: list[uuid.UUID] = []


@router.post("/predictions/{pid}/results", status_code=201)
def record_result(pid: uuid.UUID, body: ResultIn, session: Session = Db, participant_id: uuid.UUID = Participant):
    p = _own_pred(session, pid, participant_id)
    if p.status != "locked":
        raise DomainError(409, "Lock the prediction before recording a result.")
    if body.assessment not in ("consistent_with_prediction", "counts_against", "inconclusive"):
        raise DomainError(422, "Unknown assessment.")
    for oid in body.observation_ids:
        o = session.get(Observation, oid)
        if o is None or o.participant_id != participant_id:
            raise DomainError(404, "Observation not found.")
        if o.collection_date is None or o.collection_date <= p.locked_at.date():
            raise DomainError(409, "An observation collected on or before the day the prediction was locked is not a "
                                   "prospective outcome.")
    r = ResearchPredictionResult(id=uuid.uuid4(), prediction_id=p.id, result_text=body.result_text.strip(),
                                 assessment=body.assessment, observation_ids=[str(i) for i in body.observation_ids],
                                 context_ids=[str(i) for i in body.context_ids])
    session.add(r)
    records.audit(session, participant_id, "research.prediction_result_recorded", "research_prediction", p.id,
                  {"assessment": body.assessment, "observations": len(body.observation_ids)})
    session.commit()
    return _pred(session, p)

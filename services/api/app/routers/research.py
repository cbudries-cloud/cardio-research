import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_participant_id
from app.models import ResearchLiveRun, ResearchSnapshot
from app.research import live_run, runtime

router = APIRouter(prefix="/research", tags=["research"])


def _out(s: ResearchSnapshot) -> dict:
    return {"id": str(s.id), "version": s.version, "created_at": s.created_at.isoformat(),
            "runtime_version": s.runtime_version, "rules_sha256": s.rules_sha256,
            "inputs": s.inputs, "outputs": s.outputs}


@router.post("/snapshots", status_code=201)
def create_snapshot(session: Session = Depends(get_session), participant_id: uuid.UUID = Depends(get_participant_id)):
    snap = runtime.create_snapshot(session, participant_id)
    session.commit()
    return _out(snap)


@router.get("/snapshots")
def list_snapshots(session: Session = Depends(get_session), participant_id: uuid.UUID = Depends(get_participant_id)):
    rows = session.scalars(select(ResearchSnapshot).where(ResearchSnapshot.participant_id == participant_id)
                           .order_by(ResearchSnapshot.version.desc())).all()
    return [{"id": str(s.id), "version": s.version, "created_at": s.created_at.isoformat(),
             "findings": len(s.outputs.get("findings", [])), "observations": len(s.inputs.get("observations", []))}
            for s in rows]


@router.get("/snapshots/{version}")
def get_snapshot(version: int, session: Session = Depends(get_session),
                 participant_id: uuid.UUID = Depends(get_participant_id)):
    snap = session.scalar(select(ResearchSnapshot).where(ResearchSnapshot.participant_id == participant_id,
                                                         ResearchSnapshot.version == version))
    if snap is None:
        raise HTTPException(404, "Snapshot not found.")
    return _out(snap)


# --- ApoB / LDL-P live run ----------------------------------------------------------

class ApprovalIn(BaseModel):
    payload_sha256: str
    provider: str
    model: str
    endpoint: str
    approve_this_payload_for_this_run_only: bool


def _run(session: Session, run_id: uuid.UUID, participant_id: uuid.UUID) -> ResearchLiveRun:
    run = session.get(ResearchLiveRun, run_id)
    if run is None or run.participant_id != participant_id:
        raise HTTPException(404, "Live run not found.")
    return run


@router.get("/apob-ldlp/readiness")
def apob_ldlp_readiness(session: Session = Depends(get_session), participant_id: uuid.UUID = Depends(get_participant_id)):
    return live_run.readiness(session, participant_id)


@router.get("/live-runs")
def list_live_runs(kind: str = "apob_ldlp", session: Session = Depends(get_session),
                   participant_id: uuid.UUID = Depends(get_participant_id)):
    rows = session.scalars(select(ResearchLiveRun).where(ResearchLiveRun.participant_id == participant_id,
                                                         ResearchLiveRun.kind == kind)
                           .order_by(ResearchLiveRun.created_at.desc())).all()
    return [{"id": str(r.id), "status": r.status, "created_at": r.created_at.isoformat(), "model": r.model,
             "snapshot_version": live_run.snapshot_version(session, r)} for r in rows]


@router.get("/live-runs/{run_id}")
def get_live_run(run_id: uuid.UUID, session: Session = Depends(get_session),
                 participant_id: uuid.UUID = Depends(get_participant_id)):
    run = _run(session, run_id, participant_id)
    return live_run.to_out(run, live_run.snapshot_version(session, run))


@router.post("/live-runs", status_code=201)
def prepare_live_run(session: Session = Depends(get_session), participant_id: uuid.UUID = Depends(get_participant_id)):
    run = live_run.prepare(session, participant_id)
    session.commit()
    return live_run.to_out(run, live_run.snapshot_version(session, run))


@router.post("/live-runs/{run_id}/approve", status_code=202)
def approve_live_run(run_id: uuid.UUID, body: ApprovalIn, session: Session = Depends(get_session),
                     participant_id: uuid.UUID = Depends(get_participant_id)):
    _run(session, run_id, participant_id)
    run = live_run.approve(session, run_id, body.model_dump())
    session.commit()
    live_run.start(run.id)
    return live_run.to_out(run, live_run.snapshot_version(session, run))


@router.post("/live-runs/{run_id}/withdraw")
def withdraw_live_run(run_id: uuid.UUID, session: Session = Depends(get_session),
                      participant_id: uuid.UUID = Depends(get_participant_id)):
    _run(session, run_id, participant_id)
    run = live_run.withdraw(session, run_id)
    session.commit()
    return live_run.to_out(run, live_run.snapshot_version(session, run))

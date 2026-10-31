"""The single boundary through which future calculations (Milestone 3+) may read
observations.

Only observations that were accepted (by participant review or, labelled as such in
verification_method, by the automated source checks), that have not been superseded,
withdrawn or rejected, that have no successor version, that carry no blocking extraction issue
(including an unresolved specimen conflict), and that are not involved in an open review flag
are returned.
Nothing in this module performs a medical calculation.
"""

import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session, aliased

from app import vocab
from app.models import Observation, ReviewFlag


def _eligible_clause():
    open_flag = exists().where(
        ReviewFlag.status == "open",
        or_(ReviewFlag.observation_id == Observation.id, ReviewFlag.related_observation_id == Observation.id),
    )
    successor = aliased(Observation)
    has_successor = exists().where(successor.supersedes_observation_id == Observation.id)
    return (
        Observation.verification_status == "accepted",
        Observation.verified_at.is_not(None),
        Observation.verification_method.is_not(None),  # an acceptance must say how it was verified
        ~open_flag,
        # Defense in depth: acceptance already requires these, but a row with an unresolved
        # blocking issue (e.g. specimen_conflict) or with any successor version must never be
        # used, so an observation and its replacement can never both be counted.
        ~Observation.extraction_issues.has_any(array(sorted(vocab.BLOCKING_ISSUES))),
        ~has_successor,
    )


def is_calculation_input(session: Session, obs_id: uuid.UUID) -> bool:
    return session.scalar(select(Observation.id).where(Observation.id == obs_id, *_eligible_clause())) is not None


def calculation_input_observations(
    session: Session, participant_id: uuid.UUID, normalized_test_name: str | None = None
) -> list[Observation]:
    stmt = select(Observation).where(Observation.participant_id == participant_id, *_eligible_clause())
    if normalized_test_name is not None:
        stmt = stmt.where(Observation.normalized_test_name == normalized_test_name)
    return list(session.scalars(stmt.order_by(Observation.collection_date, Observation.created_at, Observation.id)).all())

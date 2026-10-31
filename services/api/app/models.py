"""ORM models. The schema itself is defined by the Alembic migrations in
migrations/versions; these mappings must stay in sync with them.

Vocabulary for the text status columns lives in app/vocab.py and is enforced
by CHECK constraints in the migration.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    original_filename: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    document_format: Mapped[str] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(Text)
    parse_message: Mapped[str | None] = mapped_column(Text)
    parser_name: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column()
    declared_date_order: Mapped[str | None] = mapped_column(Text)
    declared_collection_method: Mapped[str | None] = mapped_column(Text)
    duplicate_of_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))
    source_location: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    entry_method: Mapped[str] = mapped_column(Text)

    original_test_name: Mapped[str] = mapped_column(Text)
    normalized_test_name: Mapped[str | None] = mapped_column(Text)
    original_value: Mapped[str | None] = mapped_column(Text)
    original_unit: Mapped[str | None] = mapped_column(Text)
    value_comparator: Mapped[str | None] = mapped_column(Text)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric)
    normalized_unit: Mapped[str | None] = mapped_column(Text)
    value_origin: Mapped[str] = mapped_column(Text)

    collection_date: Mapped[date | None] = mapped_column(Date)
    collection_date_raw: Mapped[str | None] = mapped_column(Text)
    collection_date_status: Mapped[str] = mapped_column(Text)
    collection_date_interpretation: Mapped[str | None] = mapped_column(Text)
    report_date: Mapped[date | None] = mapped_column(Date)
    report_date_raw: Mapped[str | None] = mapped_column(Text)
    report_date_status: Mapped[str] = mapped_column(Text)

    specimen_type_raw: Mapped[str | None] = mapped_column(Text)
    specimen_type: Mapped[str] = mapped_column(Text)
    specimen_source: Mapped[str] = mapped_column(Text, default="none")
    inherited_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    accession_id: Mapped[str | None] = mapped_column(Text)
    collection_method: Mapped[str] = mapped_column(Text)
    collection_method_basis: Mapped[str] = mapped_column(Text)

    laboratory: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    reference_range_raw: Mapped[str | None] = mapped_column(Text)
    reference_range_low: Mapped[Decimal | None] = mapped_column(Numeric)
    reference_range_high: Mapped[Decimal | None] = mapped_column(Numeric)
    lab_flag_raw: Mapped[str | None] = mapped_column(Text)
    collection_conditions: Mapped[str | None] = mapped_column(Text)
    result_status_raw: Mapped[str | None] = mapped_column(Text)
    reported_as_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    reported_as: Mapped[str] = mapped_column(Text, default="current")
    result_type: Mapped[str] = mapped_column(Text, default="quantity")

    extraction_status: Mapped[str] = mapped_column(Text)
    extraction_issues: Mapped[list[str]] = mapped_column(JSONB, default=list)

    verification_status: Mapped[str] = mapped_column(Text, default="unverified")
    verification_note: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_method: Mapped[str | None] = mapped_column(Text)

    supersedes_observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("observations.id"))
    correction_kind: Mapped[str | None] = mapped_column(Text)
    correction_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(Text)


class ReviewFlag(Base):
    __tablename__ = "review_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    kind: Mapped[str] = mapped_column(Text)
    observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("observations.id"))
    related_observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("observations.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))
    related_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text, default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    participant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("participants.id"))
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ResearchSnapshot(Base):
    __tablename__ = "research_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    version: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    runtime_version: Mapped[str] = mapped_column(Text)
    rules_sha256: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ResearchLiveRun(Base):
    __tablename__ = "research_live_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_snapshots.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    status: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    endpoint: Mapped[str] = mapped_column(Text)
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(Text)
    local_refs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    estimate: Mapped[dict[str, Any]] = mapped_column(JSONB)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_handling: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    approval: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_id: Mapped[str | None] = mapped_column(Text)
    response_model: Mapped[str | None] = mapped_column(Text)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric)
    latency_ms: Mapped[float | None] = mapped_column()
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    citation_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    comparison: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="apob_ldlp")
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ParticipantContext(Base):
    __tablename__ = "participant_context"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    domain: Mapped[str] = mapped_column(Text)
    item: Mapped[str] = mapped_column(Text)
    value_text: Mapped[str] = mapped_column(Text)
    as_of: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("participant_context.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ResearchConversation(Base):
    __tablename__ = "research_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ResearchMessage(Base):
    __tablename__ = "research_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_conversations.id"))
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    text: Mapped[str] = mapped_column(Text)
    retrieval: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ResearchNote(Base):
    __tablename__ = "research_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    kind: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="accepted")
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("research_live_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchInvestigation(Base):
    __tablename__ = "research_investigations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    priority_id: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ResearchPrediction(Base):
    __tablename__ = "research_predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"))
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("research_investigations.id"))
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("research_live_runs.id"))
    protocol: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="draft")
    protocol_sha256: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class ResearchPredictionResult(Base):
    __tablename__ = "research_prediction_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_predictions.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    observation_ids: Mapped[list[str]] = mapped_column(JSONB)
    context_ids: Mapped[list[str]] = mapped_column(JSONB)
    result_text: Mapped[str] = mapped_column(Text)
    assessment: Mapped[str] = mapped_column(Text)

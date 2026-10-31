"""API contracts (exported to packages/schemas/openapi.json)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Num = Annotated[
    Decimal | None,
    PlainSerializer(lambda v: float(v) if v is not None else None, return_type=float | None),
]


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentOut(Orm):
    id: uuid.UUID
    original_filename: str
    content_type: str | None
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    document_format: str
    parse_status: str
    parse_message: str | None
    parser_name: str | None
    parser_version: str | None
    page_count: int | None
    declared_date_order: str | None
    declared_collection_method: str | None
    duplicate_of_document_id: uuid.UUID | None


class DocumentSummary(DocumentOut):
    candidate_count: int = 0
    unverified_count: int = 0
    accepted_count: int = 0


class ObservationOut(Orm):
    id: uuid.UUID
    participant_id: uuid.UUID
    source_document_id: uuid.UUID | None
    source_location: dict[str, Any]
    entry_method: str
    original_test_name: str
    normalized_test_name: str | None
    original_value: str | None
    original_unit: str | None
    value_comparator: str | None
    value_numeric: Num
    normalized_value: Num
    normalized_unit: str | None
    value_origin: str
    collection_date: date | None
    collection_date_raw: str | None
    collection_date_status: str
    collection_date_interpretation: str | None
    report_date: date | None
    report_date_raw: str | None
    report_date_status: str
    specimen_type_raw: str | None
    specimen_type: str
    specimen_source: str
    inherited_metadata: dict[str, Any]
    accession_id: str | None
    collection_method: str
    collection_method_basis: str
    laboratory: str | None
    method: str | None
    reference_range_raw: str | None
    reference_range_low: Num
    reference_range_high: Num
    lab_flag_raw: str | None
    collection_conditions: str | None
    result_status_raw: str | None
    reported_as_corrected: bool
    extraction_status: str
    extraction_issues: list[str]
    blocking_issues: list[str] = []
    verification_status: str
    verification_note: str | None
    verified_at: datetime | None
    verification_method: str | None = None
    reported_as: str = "current"
    result_type: str = "quantity"
    supersedes_observation_id: uuid.UUID | None
    correction_kind: str | None
    correction_reason: str | None
    created_at: datetime
    created_by: str


class FlagOut(Orm):
    id: uuid.UUID
    kind: str
    observation_id: uuid.UUID | None
    related_observation_id: uuid.UUID | None
    document_id: uuid.UUID | None
    related_document_id: uuid.UUID | None
    detail: dict[str, Any]
    status: str
    resolution: str | None
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None
    allowed_resolutions: list[str] = []


class AuditOut(Orm):
    id: int
    occurred_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: uuid.UUID
    detail: dict[str, Any]


class ObservationDetail(BaseModel):
    observation: ObservationOut
    document: DocumentOut | None
    flags: list[FlagOut]
    superseded_by: uuid.UUID | None
    history: list[ObservationOut]  # earlier versions, newest first
    audit: list[AuditOut]
    eligible_for_calculation_inputs: bool


class DocumentDetail(BaseModel):
    document: DocumentOut
    observations: list[ObservationOut]
    flags: list[FlagOut]
    replaced_candidate_count: int = 0
    current_parser_version: str | None = None
    reextract_allowed: bool = False


class AcceptIn(BaseModel):
    confirm_source_matches: bool
    note: str | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=1)


CollectionMethod = Literal["venous", "capillary", "unknown"]
SpecimenType = Literal["serum", "plasma", "whole_blood", "dried_blood_spot", "urine", "unknown"]


class CorrectIn(BaseModel):
    reason: str = Field(min_length=1)
    correction_kind: Literal["extraction_error", "lab_issued_correction"] = "extraction_error"
    test_name: str | None = None
    normalized_test_name: str | None = None
    value: str | None = None
    unit: str | None = None
    collection_date: date | None = None
    report_date: date | None = None
    specimen: str | None = None
    specimen_type: SpecimenType | None = None
    collection_method: CollectionMethod | None = None
    reference_range: str | None = None
    flag: str | None = None
    laboratory: str | None = None
    method: str | None = None
    conditions: str | None = None
    accession: str | None = None


class ManualIn(BaseModel):
    source_document_id: uuid.UUID | None = None
    source_page: int | None = None
    source_note: str | None = None
    test_name: str = Field(min_length=1)
    normalized_test_name: str | None = None
    value: str
    unit: str | None = None
    collection_date: date | None = None
    collection_date_text: str | None = None
    report_date: date | None = None
    specimen: str | None = None
    specimen_type: SpecimenType | None = None
    collection_method: CollectionMethod | None = None
    reference_range: str | None = None
    flag: str | None = None
    laboratory: str | None = None
    method: str | None = None
    conditions: str | None = None
    accession: str | None = None


class ResolveFlagIn(BaseModel):
    resolution: str
    note: str | None = None


class CalculationInput(BaseModel):
    """Shape handed to future calculations. Deliberately minimal and provenance-bearing."""

    observation_id: uuid.UUID
    normalized_test_name: str | None
    value: float | None  # None for categorical results; for bounded results this is the bound
    comparator: str | None  # "<", ">", ... : the value is a bound, never exact
    result_type: str
    value_as_written: str | None
    unit: str | None
    value_origin: str
    collection_date: date
    collection_method: str
    specimen_type: str
    specimen_source: str
    laboratory: str | None
    accession_id: str | None
    source_document_id: uuid.UUID | None
    verified_at: datetime
    verification_method: str


class Overview(BaseModel):
    documents: int
    documents_needing_manual_entry: int
    unverified: int
    unverified_blocked: int
    accepted: int
    rejected: int
    superseded: int
    open_flags: int
    last_activity_at: datetime | None

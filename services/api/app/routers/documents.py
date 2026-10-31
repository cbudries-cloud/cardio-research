import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.deps import get_participant_id, get_storage
from app.ingestion import pdf_parser
from app.models import Observation, ReviewFlag, SourceDocument
from app.routers.common import flag_out, observation_out
from app.schemas import DocumentDetail, DocumentOut, DocumentSummary
from app.services import reconciliation, records
from app.storage import LocalFileStorage

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentSummary, status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File()],
    date_order: Annotated[Literal["", "MDY", "DMY"], Form()] = "",
    collection_method: Annotated[Literal["", "venous", "capillary", "unknown"], Form()] = "",
    session: Session = Depends(get_session),
    storage: LocalFileStorage = Depends(get_storage),
    participant_id: uuid.UUID = Depends(get_participant_id),
):
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {limit // (1024 * 1024)} MB limit.")
    if not data:
        raise HTTPException(422, "File is empty.")
    doc = records.import_document(
        session, storage, participant_id, file.filename or "upload", file.content_type, data,
        date_order or None, collection_method or None,
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        storage.delete(doc.storage_key)
        raise
    return _summary(session, doc)


@router.post("/{doc_id}/reextract", response_model=DocumentSummary)
def reextract_document(
    doc_id: uuid.UUID,
    date_order: Annotated[Literal["", "MDY", "DMY"] | None, Form()] = None,
    session: Session = Depends(get_session),
    storage: LocalFileStorage = Depends(get_storage),
    participant_id: uuid.UUID = Depends(get_participant_id),
):
    doc = session.get(SourceDocument, doc_id)
    if doc is None or doc.participant_id != participant_id:
        raise HTTPException(404, "Document not found.")
    doc = records.reextract_document(session, storage, doc_id, date_order)
    session.commit()
    return _summary(session, doc)


@router.get("/{doc_id}/reconciliation")
def document_reconciliation(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage: LocalFileStorage = Depends(get_storage),
    participant_id: uuid.UUID = Depends(get_participant_id),
):
    doc = session.get(SourceDocument, doc_id)
    if doc is None or doc.participant_id != participant_id:
        raise HTTPException(404, "Document not found.")
    return reconciliation.reconcile(session, storage, doc_id)


@router.post("/{doc_id}/auto-accept")
def auto_accept_document(
    doc_id: uuid.UUID,
    session: Session = Depends(get_session),
    participant_id: uuid.UUID = Depends(get_participant_id),
):
    doc = session.get(SourceDocument, doc_id)
    if doc is None or doc.participant_id != participant_id:
        raise HTTPException(404, "Document not found.")
    result = records.auto_accept_document(session, doc_id)
    session.commit()
    return result


def _not_replaced():
    """Excludes candidates rejected because the document was re-extracted."""
    return func.coalesce(Observation.verification_note, "").not_like(f"{records.REEXTRACTION_NOTE}%")


def _summary(session: Session, doc: SourceDocument) -> DocumentSummary:
    counts = dict(session.execute(
        select(Observation.verification_status, func.count())
        .where(Observation.source_document_id == doc.id, _not_replaced())
        .group_by(Observation.verification_status)
    ).all())
    return DocumentSummary(
        **DocumentOut.model_validate(doc).model_dump(),
        candidate_count=sum(counts.values()),
        unverified_count=counts.get("unverified", 0),
        accepted_count=counts.get("accepted", 0),
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents(session: Session = Depends(get_session), participant_id=Depends(get_participant_id)):
    docs = session.scalars(
        select(SourceDocument).where(SourceDocument.participant_id == participant_id)
        .order_by(SourceDocument.uploaded_at.desc(), SourceDocument.id)
    ).all()
    return [_summary(session, d) for d in docs]


def _get_doc(session: Session, doc_id: uuid.UUID) -> SourceDocument:
    doc = session.get(SourceDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


@router.get("/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: uuid.UUID, session: Session = Depends(get_session)):
    doc = _get_doc(session, doc_id)
    all_obs = session.scalars(
        select(Observation).where(Observation.source_document_id == doc_id).order_by(Observation.created_at, Observation.id)
    ).all()
    replaced = [o for o in all_obs if (o.verification_note or "").startswith(records.REEXTRACTION_NOTE)]
    observations = [o for o in all_obs if o not in replaced]
    flags = session.scalars(
        select(ReviewFlag).where((ReviewFlag.document_id == doc_id) | (ReviewFlag.related_document_id == doc_id))
        .order_by(ReviewFlag.created_at, ReviewFlag.id)
    ).all()
    return DocumentDetail(
        document=DocumentOut.model_validate(doc),
        observations=[observation_out(o) for o in observations],
        flags=[flag_out(f) for f in flags],
        replaced_candidate_count=len(replaced),
        current_parser_version=records.current_parser_version(doc.document_format),
        reextract_allowed=records.reextract_allowed(all_obs) and doc.document_format in ("csv", "pdf"),
    )


@router.get("/{doc_id}/original")
def get_original(doc_id: uuid.UUID, session: Session = Depends(get_session),
                 storage: LocalFileStorage = Depends(get_storage)):
    doc = _get_doc(session, doc_id)
    media = {"pdf": "application/pdf", "csv": "text/csv; charset=utf-8"}.get(doc.document_format,
                                                                         "application/octet-stream")
    headers = {"Content-Disposition": f'attachment; filename="document-{doc.id}"'}
    if doc.document_format == "pdf":
        # Inline so the browser's PDF viewer can show it; a sandbox CSP would block that viewer.
        headers["Content-Disposition"] = f'inline; filename="document-{doc.id}.pdf"'
    else:
        headers["Content-Security-Policy"] = "sandbox"
    return Response(storage.get(doc.storage_key), media_type=media, headers=headers)


@router.get("/{doc_id}/pages/{page}/image")
def get_page_image(doc_id: uuid.UUID, page: int, session: Session = Depends(get_session),
                   storage: LocalFileStorage = Depends(get_storage)):
    doc = _get_doc(session, doc_id)
    if doc.document_format != "pdf":
        raise HTTPException(404, "Page images are available for PDF documents only.")
    try:
        png = pdf_parser.render_page_png(storage.get(doc.storage_key), page)
    except IndexError:
        raise HTTPException(404, "Page not found.")
    return Response(png, media_type="image/png")

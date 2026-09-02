import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import Document, User
from app.db.session import get_db
from app.schemas.document import DocumentCreateResponse, DocumentOut, SearchResponse
from app.services.ingest_service import IngestService
from app.services.retriever import Retriever

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentCreateResponse)
@limiter.limit("10/minute")
async def upload_document(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    file: UploadFile = File(...),
    title: str | None = Form(None),
):
    # Enforce size limit
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large, max {settings.MAX_UPLOAD_SIZE_MB} MB")

    doc_title = title or file.filename or "Untitled"
    try:
        doc = await IngestService.ingest_file_bytes(
            db, current_user.id, doc_title, file.filename or "file", contents, file.content_type or "text/plain"
        )
        await db.commit()
        await db.refresh(doc)
        return DocumentCreateResponse(document=DocumentOut.model_validate(doc), chunks=doc.total_chunks)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception:
        logger.exception("Ingest failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to ingest document")


@router.post("/ingest-text", response_model=DocumentCreateResponse)
@limiter.limit("10/minute")
async def ingest_text(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    title: str = Form(...),
    content: str = Form(...),
    source: str | None = Form(None),
):
    try:
        doc = await IngestService.ingest_text(db, current_user.id, title, source, content)
        await db.commit()
        await db.refresh(doc)
        return DocumentCreateResponse(document=DocumentOut.model_validate(doc), chunks=doc.total_chunks)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception:
        logger.exception("Ingest text failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to ingest")


@router.get("", response_model=list[DocumentOut])
@limiter.limit("30/minute")
async def list_documents(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    result = await db.execute(
        select(Document).where(Document.user_id == current_user.id).order_by(Document.created_at.desc()).limit(limit).offset(offset)
    )
    docs = result.scalars().all()
    return docs


@router.get("/search", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search_documents(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
    q: str = Query(..., min_length=1, description="Search query"),
    k: int = Query(4, ge=1, le=10),
):
    context, citations = await Retriever.search_with_citations(db, current_user.id, q, k=k)
    results = await Retriever.search(db, current_user.id, q, k=k)
    return SearchResponse(
        query=q,
        results=[
            {
                "chunk_id": r["chunk_id"],
                "document_id": r["document_id"],
                "title": r["title"],
                "content": r["content"],
                "score": r["score"],
                "chunk_index": r["chunk_index"],
            }
            for r in results
        ],
        context=context,
        citations=citations,
    )


@router.get("/{document_id}", response_model=DocumentOut)
@limiter.limit("30/minute")
async def get_document(
    request: Request,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    result = await db.execute(select(Document).where(Document.id == document_id, Document.user_id == current_user.id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/{document_id}")
@limiter.limit("10/minute")
async def delete_document(
    request: Request,
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    result = await db.execute(select(Document).where(Document.id == document_id, Document.user_id == current_user.id))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
    return {"detail": "deleted"}

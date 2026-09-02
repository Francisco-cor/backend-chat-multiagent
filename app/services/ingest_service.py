import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Document, DocumentChunk
from app.services.embedding_service import embedding_service
from app.services.token_counter import count_tokens

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunk = text[start:end]
        # Try to break at sentence or paragraph boundary if possible
        if end < n:
            # Look for last period or newline within overlap
            last_period = chunk.rfind(". ")
            last_nl = chunk.rfind("\n")
            cut = max(last_period, last_nl)
            if cut > chunk_size - overlap - 100 and cut > 0:
                chunk = chunk[: cut + 1]
                end = start + len(chunk)
        chunks.append(chunk.strip())
        if end >= n:
            break
        start = end - overlap
        if start < 0:
            start = 0
    # Filter empty
    return [c for c in chunks if c]


class IngestService:
    @staticmethod
    async def ingest_text(
        db: AsyncSession,
        user_id: int,
        title: str,
        source: str | None,
        content: str,
    ) -> Document:
        chunks = chunk_text(content, settings.RAG_CHUNK_SIZE, settings.RAG_CHUNK_OVERLAP)
        if not chunks:
            raise ValueError("No content to ingest")

        doc = Document(user_id=user_id, title=title, source=source, total_chunks=len(chunks))
        db.add(doc)
        await db.flush()
        await db.refresh(doc)

        # Embed batch
        embeddings = await embedding_service.embed_batch(chunks)

        for idx, (chunk, vec) in enumerate(zip(chunks, embeddings)):
            token_count = count_tokens(chunk)
            emb_str = embedding_service.serialize(vec)
            db_chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=idx,
                content=chunk,
                embedding=emb_str,
                token_count=token_count,
            )
            db.add(db_chunk)

        await db.flush()
        logger.info(f"Ingested doc {doc.id} title={title} chunks={len(chunks)}")
        return doc

    @staticmethod
    async def ingest_file_bytes(
        db: AsyncSession,
        user_id: int,
        title: str,
        filename: str,
        content_bytes: bytes,
        mime_type: str,
    ) -> Document:
        # Simple file handling: decode as utf-8 ignore, for pdf keep as text (future: use pypdf)
        try:
            text = content_bytes.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        # If pdf and text looks binary, try to extract with simple fallback
        if filename.lower().endswith(".pdf") and len(text) < 100:
            # For MVP, store raw bytes as base64 snippet
            text = f"[PDF content from {filename} — binary preview]\n" + text[:2000]
        return await IngestService.ingest_text(db, user_id, title, filename, text)

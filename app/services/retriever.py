import logging
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Document, DocumentChunk
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class Retriever:
    @staticmethod
    async def search(
        db: AsyncSession,
        user_id: int,
        query: str,
        k: int | None = None,
    ) -> list[dict[str, Any]]:
        k = k or settings.RAG_TOP_K
        query_vec = await embedding_service.embed_text(query)

        # Fetch all chunks for user
        result = await db.execute(
            select(DocumentChunk, Document.title)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.user_id == user_id)
        )
        rows = result.all()
        scored = []
        for chunk, title in rows:
            if not chunk.embedding:
                continue
            vec = embedding_service.deserialize(chunk.embedding)
            if not vec:
                continue
            score = cosine_similarity(query_vec, vec)
            scored.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "title": title,
                    "content": chunk.content,
                    "score": score,
                    "chunk_index": chunk.chunk_index,
                }
            )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:k]

    @staticmethod
    async def search_with_citations(
        db: AsyncSession, user_id: int, query: str, k: int | None = None
    ) -> tuple[str, list[dict[str, Any]]]:
        results = await Retriever.search(db, user_id, query, k=k)
        if not results:
            return "", []
        # Format citations [1], [2]...
        context_parts = []
        citations = []
        for i, r in enumerate(results, 1):
            context_parts.append(f"[{i}] {r['content']} (source: {r['title']}#{r['chunk_id']})")
            citations.append(
                {
                    "id": i,
                    "chunk_id": r["chunk_id"],
                    "document_id": r["document_id"],
                    "title": r["title"],
                    "content": r["content"][:500],
                    "score": round(r["score"], 4),
                }
            )
        context = "\n\n".join(context_parts)
        return context, citations

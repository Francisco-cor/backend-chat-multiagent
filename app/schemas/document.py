from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    title: str
    source: str | None = None
    total_chunks: int
    created_at: datetime


class DocumentChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    document_id: int
    chunk_index: int
    content: str
    token_count: int | None = None
    created_at: datetime


class DocumentCreateResponse(BaseModel):
    document: DocumentOut
    chunks: int


class SearchResult(BaseModel):
    chunk_id: int
    document_id: int
    title: str
    content: str
    score: float
    chunk_index: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    context: str
    citations: list[dict]

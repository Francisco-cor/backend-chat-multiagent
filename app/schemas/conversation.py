from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    tokens: int | None = None
    cost_usd: float | None = None
    created_at: datetime
    legacy_session_id: str | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str | None = None
    model: str | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    total_tokens: int
    total_cost_usd: float
    legacy_session_id: str | None = None


class ConversationCreate(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128, description="Client session id to map to conversation")
    title: str | None = Field(None, max_length=255)
    model: str | None = None


class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class PaginatedConversations(BaseModel):
    items: list[ConversationOut]
    next_cursor: int | None = None
    has_more: bool


class PaginatedMessages(BaseModel):
    items: list[MessageOut]
    next_cursor: int | None = None
    has_more: bool

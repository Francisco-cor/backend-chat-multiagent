from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=lambda: ["chat:write", "chat:read"])
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="NULL = no expiry")


class ApiKeyCreateResponse(BaseModel):
    id: int
    name: str
    key: str  # plain key shown once
    key_prefix: str
    scopes: List[str]
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    model_config = {"from_attributes": True}

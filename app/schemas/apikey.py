from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["my-cli", "prod-key"])
    scopes: List[str] = Field(default_factory=lambda: ["chat:write", "chat:read"], examples=[["chat:write", "chat:read"], ["chat:read"]], description="Allowed: chat:read/write, documents:read/write, admin:read/write")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="NULL = no expiry", examples=[30, 90])


class ApiKeyCreateResponse(BaseModel):
    id: int = Field(..., examples=[1])
    name: str = Field(..., examples=["my-cli"])
    key: str = Field(..., description="Plain key shown once — store securely!", examples=["sk_abc123..."])
    key_prefix: str = Field(..., examples=["sk_abc123"])
    scopes: List[str] = Field(..., examples=[["chat:write"]])
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

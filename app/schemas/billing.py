from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class UsageOut(BaseModel):
    id: int
    model: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    request_id: Optional[str] = None
    endpoint: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class UsageSummary(BaseModel):
    total_tokens: int
    total_cost_usd: float
    requests: int
    period_days: Optional[int] = None

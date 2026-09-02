from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class OrchestrateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    prompt: str = Field(..., min_length=1, max_length=32000)
    model: Optional[str] = Field(None, description="Base model for agents, e.g. gemini-3.1-pro")
    strategy: str = Field("auto", description="auto | sequential | parallel | direct or comma-separated agent list")
    use_search: bool = False
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    file_base64: Optional[str] = None
    file_mime_type: Optional[str] = None


class AgentTrace(BaseModel):
    agent: str
    output: str
    error: bool = False
    model_config = ConfigDict(from_attributes=True)


class OrchestrateResponse(BaseModel):
    session_id: str
    reply: str
    trace: List[AgentTrace]
    strategy: str
    model_used: str


class AgentInfo(BaseModel):
    name: str
    description: str
    model: str
    temperature: float
    tools: List[str]
    max_history: int

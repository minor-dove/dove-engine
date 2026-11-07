"""
Long-term conversational memory schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    session_id: Optional[str] = None
    message_id: Optional[int] = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: Optional[str] = None
    message_id: Optional[int] = None
    content: str
    is_active: bool
    is_false_trigger: bool
    created_at: datetime


class MemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)

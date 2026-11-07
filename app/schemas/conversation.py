"""
Conversation schemas for multi-turn dialogue management.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class MessageBase(BaseModel):
    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(default="", description="Message text content")
    mood_context: Optional[str] = Field(default=None, description="Optional mood context attached to this turn")


class MessageCreate(BaseModel):
    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(..., min_length=1, description="Message text content")
    mood_context: Optional[str] = Field(default=None, description="Optional mood context attached to this turn")


class MessageResponse(MessageBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    delivery_status: str
    created_at: datetime


class SessionCreate(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    trigger_type: str = Field(default="user_initiated")


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    is_active: bool
    trigger_type: str
    is_false_trigger: bool
    started_at: datetime
    ended_at: Optional[datetime] = None
    messages: List[MessageResponse] = []


class SendMessageRequest(BaseModel):
    """
    Used by application REST API or simulated voice transcript to interact with DOVE.
    """
    device_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, description="User utterance / message")
    session_id: Optional[str] = Field(default=None, description="Existing session ID to continue, or None to auto-resume/create")


class SendMessageResponse(BaseModel):
    session_id: str
    reply: str
    trigger_type: str
    mood_context: Optional[str] = None
    created_at: datetime


class MarkFalseTriggerRequest(BaseModel):
    is_false_trigger: bool = Field(default=True, description="Mark as false trigger to purge/exclude derived memories")

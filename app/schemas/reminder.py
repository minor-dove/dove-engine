"""
Reminder schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class ReminderBase(BaseModel):
    message: str = Field(..., min_length=1, max_length=512)
    scheduled_time: datetime = Field(..., description="UTC scheduled time for delivery")


class ReminderCreate(ReminderBase):
    pass


class ReminderUpdate(BaseModel):
    message: Optional[str] = Field(default=None, min_length=1, max_length=512)
    scheduled_time: Optional[datetime] = None
    status: Optional[str] = Field(default=None, description="'pending', 'delivered', 'acknowledged', 'cancelled', 'failed'")


class ReminderResponse(ReminderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    retry_count: int
    last_attempt_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime

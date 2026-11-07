"""
Routine schemas.
"""

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class RoutineExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    routine_type: str
    scheduled_for: datetime
    executed_at: datetime
    status: str


class RoutineTriggerRequest(BaseModel):
    routine_type: str = Field(..., description="'morning', 'midday', 'evening', or 'night'")
    device_id: str = Field(..., min_length=1, max_length=64)

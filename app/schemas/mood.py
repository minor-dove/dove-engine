"""
Mood ingestion schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.models.mood import EMOTION_MAP
from app.core.security import FORBIDDEN_PRIVACY_KEYS


class MoodEventCreate(BaseModel):
    """
    Payload sent by the ESP32 edge device every minute.
    Contains ONLY classification ID and metadata.
    """
    model_config = ConfigDict(extra="forbid")  # Strictly forbids unknown keys to prevent accidental payload injection

    event_id: str = Field(..., min_length=1, max_length=128, description="Unique client-generated event UUID for deduplication")
    device_id: str = Field(..., min_length=1, max_length=64, description="Device serial or identifier")
    mood_id: int = Field(..., ge=0, le=6, description="0:Angry, 1:Disgust, 2:Fear, 3:Happy, 4:Sad, 5:Surprise, 6:Neutral")
    recorded_at: datetime = Field(..., description="UTC timestamp of the observation on the edge device")

    @field_validator("mood_id")
    def validate_mood_id(cls, v: int) -> int:
        if v not in EMOTION_MAP:
            raise ValueError(f"Invalid mood_id {v}. Must be an integer between 0 and 6.")
        return v


class MoodEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    device_id: str
    mood_id: int
    emotion: str
    recorded_at: datetime
    received_at: datetime
    is_valid: bool


class MoodStreakResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: str
    mood_id: int
    emotion: str
    current_count: int
    last_event_time: Optional[datetime] = None
    qualifying_streak_triggered: bool

"""
User preference schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class UserPreferenceBase(BaseModel):
    quiet_hours_start: str = Field(default="22:00", pattern=r"^\d{2}:\d{2}$")
    quiet_hours_end: str = Field(default="07:00", pattern=r"^\d{2}:\d{2}$")
    proactive_enabled: bool = Field(default=True)
    cooldown_minutes: int = Field(default=30, ge=5, le=1440)
    timezone: str = Field(default="Asia/Kolkata")
    morning_time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    midday_time: str = Field(default="13:00", pattern=r"^\d{2}:\d{2}$")
    evening_time: str = Field(default="19:00", pattern=r"^\d{2}:\d{2}$")
    night_time: str = Field(default="22:30", pattern=r"^\d{2}:\d{2}$")
    night_enabled: bool = Field(default=False)


class UserPreferenceUpdate(BaseModel):
    quiet_hours_start: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    quiet_hours_end: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    proactive_enabled: Optional[bool] = None
    cooldown_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    timezone: Optional[str] = None
    morning_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    midday_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    evening_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    night_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    night_enabled: Optional[bool] = None


class UserPreferenceResponse(UserPreferenceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: datetime

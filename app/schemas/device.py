"""
Device schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class DeviceBase(BaseModel):
    name: str = Field(default="DOVE Desk Pet", max_length=128)
    firmware_version: Optional[str] = Field(default=None, max_length=32)


class DeviceCreate(DeviceBase):
    id: str = Field(..., min_length=1, max_length=64, description="Unique device identifier (e.g. dove-esp32-01)")


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    status: Optional[str] = Field(default=None, max_length=32)
    firmware_version: Optional[str] = Field(default=None, max_length=32)


class DeviceResponse(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    last_seen_at: Optional[datetime] = None
    created_at: datetime

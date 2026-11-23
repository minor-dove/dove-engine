"""
Response schemas for the companion-app endpoints (history, trends, device status, mood summary).
All scores are *perceived stress* indicators derived only from spoken answers, never a diagnosis.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SessionSummary(BaseModel):
    session_id: str
    device_id: str
    status: str = Field(description="active | completed | incomplete | aborted")
    local_date: date
    started_at: datetime
    ended_at: Optional[datetime] = None
    daypart: Optional[str] = None
    score: Optional[float] = Field(default=None, description="0-100 perceived stress, set on completion")
    band: Optional[str] = None
    answered: int
    total: int
    summary: Optional[str] = Field(default=None, description="One-line recap written after the session")
    preview: Optional[str] = Field(default=None, description="First thing Dove said, for list previews")
    message_count: int


class SessionListResponse(BaseModel):
    device_id: str
    total: int
    sessions: List[SessionSummary]
    disclaimer: str


class TranscriptMessage(BaseModel):
    id: int
    role: str = Field(description="user | assistant")
    content: str
    created_at: datetime


class SessionTranscriptResponse(BaseModel):
    session: SessionSummary
    messages: List[TranscriptMessage]
    disclaimer: str


class DayEntry(BaseModel):
    date: date
    day_score: Optional[float] = None
    band: Optional[str] = None
    status: str = Field(description="ok | no_data")
    completed_sessions: int


class DayHistoryResponse(BaseModel):
    device_id: str
    today: date = Field(description="Current day in the user's timezone")
    days: List[DayEntry] = Field(description="Oldest first, one entry per calendar day in the range")
    average_score: Optional[float] = Field(default=None, description="Mean of days that have data")
    previous_average_score: Optional[float] = Field(default=None, description="Same for the preceding range")
    trend: Optional[str] = Field(default=None, description="up | down | flat | null when not comparable")
    disclaimer: str


class ActiveSessionInfo(BaseModel):
    session_id: str
    started_at: datetime
    answered: int
    total: int


class DeviceStatusResponse(BaseModel):
    device_id: str
    registered: bool
    name: Optional[str] = None
    firmware_version: Optional[str] = None
    connection: str = Field(description="online | offline | unknown")
    last_seen_at: Optional[datetime] = None
    present: bool = False
    privacy_on: bool = False
    privacy_since: Optional[datetime] = None
    today: date
    completed_today: int
    active_session: Optional[ActiveSessionInfo] = None
    server_time: datetime


class MoodBucket(BaseModel):
    start: datetime
    total: int
    counts: Dict[str, int]


class MoodSummaryResponse(BaseModel):
    device_id: str
    period: str
    since: datetime
    total: int
    counts: Dict[str, int]
    buckets: List[MoodBucket]
    note: str = "Expression signals only frame Dove's questions; they never change your stress score."

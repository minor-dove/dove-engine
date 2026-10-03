"""
Mood models: Ingestion records and streak tracking.
Supports exact sustained Angry/Sad trigger logic.
"""

from datetime import datetime, timezone
from typing import Dict
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index
from app.core.database import Base

EMOTION_MAP: Dict[int, str] = {
    0: "Angry",
    1: "Disgust",
    2: "Fear",
    3: "Happy",
    4: "Sad",
    5: "Surprise",
    6: "Neutral"
}


class MoodEvent(Base):
    """
    Individual mood observation ingested from the edge device.
    Strictly records classification ID without any camera or face data.
    """
    __tablename__ = "mood_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(128), unique=True, nullable=False, index=True)  # Deduplication ID
    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    mood_id = Column(Integer, nullable=False)
    emotion = Column(String(32), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False, index=True)
    received_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    is_valid = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_mood_events_device_recorded", "device_id", "recorded_at"),
    )

    def __repr__(self) -> str:
        return f"<MoodEvent(event_id='{self.event_id}', mood='{self.emotion}', at='{self.recorded_at}')>"


class MoodStreak(Base):
    """
    Tracks consecutive observations of a specific mood on a device.
    Used for 10-consecutive Angry or Sad trigger qualification.
    """
    __tablename__ = "mood_streaks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    mood_id = Column(Integer, nullable=False)  # 0 for Angry, 4 for Sad, etc.
    emotion = Column(String(32), nullable=False)
    current_count = Column(Integer, nullable=False, default=0)
    last_event_time = Column(DateTime(timezone=True), nullable=True)
    qualifying_streak_triggered = Column(Boolean, nullable=False, default=False)  # Prevents repeated triggers
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_mood_streaks_device_mood", "device_id", "mood_id", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<MoodStreak(device='{self.device_id}', mood='{self.emotion}', "
            f"count={self.current_count}, triggered={self.qualifying_streak_triggered})>"
        )

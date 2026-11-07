"""
Stress assessment models.
A StressSession is a structured, scored conversation (4-6 items). Scores come ONLY from
the user's answers; mood/emotion data is never stored here or used in scoring.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from app.core.database import Base


class StressSession(Base):
    __tablename__ = "stress_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_session_id = Column(String(36), ForeignKey("conversation_sessions.id", ondelete="SET NULL"), nullable=True)
    local_date = Column(Date, nullable=False, index=True)       # user-local day this session counts toward
    status = Column(String(16), nullable=False, default="active")  # active | completed | incomplete | aborted
    item_plan = Column(Text, nullable=False)                    # JSON list of item ids to ask, in order
    current_index = Column(Integer, nullable=False, default=0)
    clarify_used = Column(Boolean, nullable=False, default=False)
    score = Column(Float, nullable=True)                        # 0-100, set on completion
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)

    responses = relationship("StressItemResponse", back_populates="session",
                             cascade="all, delete-orphan", order_by="StressItemResponse.id")

    __table_args__ = (Index("ix_stress_sessions_device_date", "device_id", "local_date"),)


class StressItemResponse(Base):
    __tablename__ = "stress_item_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("stress_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, nullable=False)
    value = Column(Integer, nullable=True)        # 0-4 raw answer scale, None = dropped/unscorable
    confidence = Column(Float, nullable=True)
    evidence = Column(Text, nullable=True)        # short quote from the user's answer
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    session = relationship("StressSession", back_populates="responses")

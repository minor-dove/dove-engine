"""
Reminder model: First-class database entity for reminders and scheduled alerts.
Supports safe delivery, retry tracking, and persistent scheduling recovery.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Index
from app.core.database import Base


class Reminder(Base):
    """
    Persistent scheduled reminder record.
    Independent of proactive conversation cooldown.
    """
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message = Column(String(512), nullable=False)
    scheduled_time = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, delivered, acknowledged, cancelled, failed
    retry_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_reminders_status_time", "status", "scheduled_time"),
    )

    def __repr__(self) -> str:
        return f"<Reminder(id={self.id}, msg='{self.message}', status='{self.status}', time='{self.scheduled_time}')>"

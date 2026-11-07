"""
Routine execution model: Tracks scheduled daily routines history.
Prevents duplicate daily routines.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Index
from app.core.database import Base


class RoutineExecution(Base):
    """
    Log of daily routine triggers (morning, midday, evening, night).
    Used to prevent duplicate routines on the same calendar day.
    """
    __tablename__ = "routine_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    routine_type = Column(String(32), nullable=False)  # morning, midday, evening, night
    scheduled_for = Column(DateTime(timezone=True), nullable=False, index=True)
    executed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status = Column(String(32), nullable=False, default="completed")  # completed, skipped, failed

    __table_args__ = (
        Index("ix_routines_type_date", "routine_type", "scheduled_for"),
    )

    def __repr__(self) -> str:
        return f"<RoutineExecution(type='{self.routine_type}', scheduled='{self.scheduled_for}', status='{self.status}')>"

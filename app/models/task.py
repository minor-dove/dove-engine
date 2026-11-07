"""
Task model: First-class database entity for user tasks.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from app.core.database import Base


class TaskItem(Base):
    """
    Structured record of a user task or goal.
    Provides authoritative task data independent of LLM memory.
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="pending", index=True)  # pending, completed, cancelled
    due_date = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_tasks_status_due", "status", "due_date"),
    )

    def __repr__(self) -> str:
        return f"<TaskItem(id={self.id}, title='{self.title}', status='{self.status}')>"

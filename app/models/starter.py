"""
Conversation starter library model.
Stores natural, non-judgmental starters for mood and routine check-ins.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Index
from app.core.database import Base


class ConversationStarter(Base):
    """
    Configurable repository of friendly, non-judgmental conversational prompts.
    Rotated based on least recent usage.
    """
    __tablename__ = "conversation_starters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(32), nullable=False, index=True)  # sad, angry, happy, neutral, morning, midday, evening, night, context
    text = Column(String(512), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_starters_category_active", "category", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<ConversationStarter(id={self.id}, cat='{self.category}', uses={self.usage_count})>"

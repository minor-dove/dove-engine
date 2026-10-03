"""
Conversation session and message models.
Preserves multi-turn dialogue history and tracks false-trigger flags.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class ConversationSession(Base):
    """
    Represents an ongoing or completed conversational session with DOVE.
    Supports multi-turn interaction until closed or timed out.
    """
    __tablename__ = "conversation_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    trigger_type = Column(String(64), nullable=False, default="user_initiated")  # user_initiated, mood_angry, mood_sad, routine_morning, etc.
    is_false_trigger = Column(Boolean, nullable=False, default=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)

    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan", order_by="ConversationMessage.id")
    memories = relationship("LongTermMemory", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ConversationSession(id='{self.id}', active={self.is_active}, false_trigger={self.is_false_trigger})>"


class ConversationMessage(Base):
    """
    Single turn in a conversation session (user speech or DOVE's reply).
    """
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    mood_context = Column(String(32), nullable=True)  # Contextual mood tag at time of turn
    delivery_status = Column(String(32), nullable=False, default="delivered")  # delivered, failed, pending
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    session = relationship("ConversationSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ConversationMessage(id={self.id}, role='{self.role}', session='{self.session_id}')>"

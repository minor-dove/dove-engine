"""
Long-term semantic memory model.
Extracts confirmed facts and preferences, with provenance tracking and false-trigger exclusion.
Supports pgvector in PostgreSQL and serialized vectors in SQLite.
"""

from datetime import datetime, timezone
import json
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, TypeDecorator
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.config import settings

# Custom type decorator that stores embeddings as pgvector Vector in PostgreSQL or JSON text in SQLite
class EmbeddingType(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector
                return dialect.type_descriptor(Vector(settings.EMBEDDING_DIMENSION))
            except Exception:
                return dialect.type_descriptor(Text())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Optional[List[float]], dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect) -> Optional[List[float]]:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return None
        return list(value)


class LongTermMemory(Base):
    """
    Stores long-term conversational knowledge, user preferences, and facts.
    Maintains strict provenance back to the originating conversation session.
    """
    __tablename__ = "long_term_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    embedding = Column(EmbeddingType, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_false_trigger = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    session = relationship("ConversationSession", back_populates="memories")

    def __repr__(self) -> str:
        return f"<LongTermMemory(id={self.id}, active={self.is_active}, false_trigger={self.is_false_trigger})>"

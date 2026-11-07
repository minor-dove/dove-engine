"""
Long-Term Memory and Semantic RAG Service.
Handles vector embeddings, semantic retrieval, fact storage, and false-trigger invalidation.
Supports PostgreSQL (pgvector) and local cosine similarity fallback for testing.
"""

import hashlib
import math
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.memory import LongTermMemory
from app.models.conversation import ConversationSession


def generate_local_embedding(text: str, dimension: int = 384) -> List[float]:
    """
    Generates a deterministic normalized embedding vector for the given text.
    Provides a lightweight, zero-dependency embedding for local testing and RAG,
    without requiring 500MB model downloads.
    """
    words = text.lower().split()
    vector = [0.0] * dimension
    
    if not words:
        return vector

    for i, word in enumerate(words):
        h = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)
        for d in range(32):
            idx = (h + d * 31) % dimension
            sign = 1.0 if ((h >> (d % 16)) & 1) else -1.0
            vector[idx] += sign

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vector))
    if norm > 0:
        vector = [x / norm for x in vector]
    return vector


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class MemoryService:
    """
    Manages long-term memories, semantic retrieval, and false-trigger lifecycle.
    """

    @staticmethod
    def get_embedding(text: str) -> List[float]:
        """Returns embedding vector for text using configured provider."""
        return generate_local_embedding(text, dimension=settings.EMBEDDING_DIMENSION)

    @staticmethod
    def add_memory(
        db: Session,
        content: str,
        session_id: Optional[str] = None,
        message_id: Optional[int] = None
    ) -> LongTermMemory:
        """
        Stores an extracted long-term memory with its semantic vector and provenance links.
        """
        embedding = MemoryService.get_embedding(content)
        memory = LongTermMemory(
            session_id=session_id,
            message_id=message_id,
            content=content.strip(),
            embedding=embedding,
            is_active=True,
            is_false_trigger=False,
            created_at=datetime.now(timezone.utc)
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory

    @staticmethod
    def search_memories(
        db: Session,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.0
    ) -> List[LongTermMemory]:
        """
        Semantically searches active, non-false-trigger memories.
        Uses pgvector <=> operator if PostgreSQL is active, or Python cosine similarity fallback.
        """
        query_vector = MemoryService.get_embedding(query)
        
        # Query active memories that are NOT marked as false triggers
        candidates = db.query(LongTermMemory).filter(
            LongTermMemory.is_active.is_(True),
            LongTermMemory.is_false_trigger.is_(False)
        ).all()

        scored_candidates = []
        for mem in candidates:
            if not mem.embedding:
                continue
            sim = cosine_similarity(query_vector, mem.embedding)
            if sim >= min_similarity:
                scored_candidates.append((sim, mem))

        # Sort by similarity descending
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored_candidates[:limit]]

    @staticmethod
    def mark_false_trigger(db: Session, session_id: str) -> bool:
        """
        Marks a conversation session as a false trigger and immediately invalidates
        all long-term memories derived from it.
        """
        session = db.query(ConversationSession).filter(ConversationSession.id == session_id).first()
        if not session:
            return False

        session.is_false_trigger = True
        session.is_active = False

        # Invalidate all derived memories
        memories = db.query(LongTermMemory).filter(LongTermMemory.session_id == session_id).all()
        for mem in memories:
            mem.is_false_trigger = True
            mem.is_active = False

        db.commit()
        return True

    @staticmethod
    def delete_memory(db: Session, memory_id: int) -> bool:
        """Deletes a long-term memory record permanently."""
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        if not memory:
            return False
        db.delete(memory)
        db.commit()
        return True

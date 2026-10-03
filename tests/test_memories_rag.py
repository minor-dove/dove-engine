"""
Long-Term Memory and RAG Tests.
Validates semantic vector retrieval, provenance tracking,
false-trigger invalidation, and memory deletion.
"""

from app.services.memory_service import MemoryService
from app.models.conversation import ConversationSession
from app.models.memory import LongTermMemory


def test_add_and_search_memory(db_session):
    """
    Test storing a long-term memory and retrieving it via semantic similarity.
    """
    mem1 = MemoryService.add_memory(
        db=db_session,
        content="User loves drinking chamomile tea while studying"
    )
    mem2 = MemoryService.add_memory(
        db=db_session,
        content="User is preparing for a physics exam on Friday"
    )

    # Search for studying tea
    results = MemoryService.search_memories(db=db_session, query="tea beverage drink", limit=2)
    assert len(results) > 0
    assert results[0].id == mem1.id
    assert "chamomile tea" in results[0].content


def test_false_trigger_purges_derived_memories(db_session):
    """
    When a conversation is marked as a false trigger, all derived memories
    must be marked is_false_trigger=True, is_active=False, and excluded from RAG.
    """
    # Create conversation session
    session = ConversationSession(
        device_id="dove-esp32-01",
        is_active=True,
        trigger_type="mood_angry"
    )
    db_session.add(session)
    db_session.commit()

    # Add memory derived from this session
    mem = MemoryService.add_memory(
        db=db_session,
        content="User mentioned feeling frustrated with the math problem",
        session_id=session.id
    )
    assert mem.is_active is True
    assert mem.is_false_trigger is False

    # Mark session as false trigger
    success = MemoryService.mark_false_trigger(db=db_session, session_id=session.id)
    assert success is True

    # Verify session is marked false trigger
    db_session.refresh(session)
    assert session.is_false_trigger is True
    assert session.is_active is False

    # Verify memory is marked false trigger and inactive
    db_session.refresh(mem)
    assert mem.is_false_trigger is True
    assert mem.is_active is False

    # Verify it is excluded from semantic search
    search_results = MemoryService.search_memories(db=db_session, query="frustrated with math problem")
    assert not any(m.id == mem.id for m in search_results)


def test_delete_memory(db_session):
    """
    Test deleting a memory record permanently.
    """
    mem = MemoryService.add_memory(db=db_session, content="Temporary test memory to delete")
    mem_id = mem.id

    assert db_session.query(LongTermMemory).filter(LongTermMemory.id == mem_id).first() is not None
    deleted = MemoryService.delete_memory(db=db_session, memory_id=mem_id)
    assert deleted is True

    assert db_session.query(LongTermMemory).filter(LongTermMemory.id == mem_id).first() is None

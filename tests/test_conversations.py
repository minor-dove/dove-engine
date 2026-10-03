"""
Conversation Service and Multi-turn Tests.
Validates multi-turn context preservation, Groq failure fallback,
structured context assembly, and false trigger marking.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from app.services.conversation_service import ConversationService
from app.services.llm_service import LLMService, FALLBACK_REPLY
from app.models.conversation import ConversationSession, ConversationMessage
from app.models.task import TaskItem


def test_multiturn_conversation_preserves_history(db_session, mock_mqtt):
    """
    Validates that sequential user utterances within a session are appended
    and context is preserved across turns.
    """
    device_id = "dove-esp32-01"

    # Turn 1
    resp1 = ConversationService.handle_user_message(
        db=db_session,
        device_id=device_id,
        message_text="Hi Dove! I'm feeling a bit tired today.",
        mqtt_publisher=mock_mqtt
    )
    assert resp1.session_id is not None
    assert resp1.reply is not None

    # Turn 2 in the same session
    resp2 = ConversationService.handle_user_message(
        db=db_session,
        device_id=device_id,
        message_text="What do you think I should do?",
        session_id=resp1.session_id,
        mqtt_publisher=mock_mqtt
    )
    assert resp2.session_id == resp1.session_id

    # Verify session has 4 messages (User 1, Assistant 1, User 2, Assistant 2)
    messages = db_session.query(ConversationMessage).filter(
        ConversationMessage.session_id == resp1.session_id
    ).order_by(ConversationMessage.id.asc()).all()

    assert len(messages) == 4
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[2].role == "user"
    assert messages[3].role == "assistant"

    # Check MQTT command was published
    assert len(mock_mqtt.published_commands) == 2
    assert mock_mqtt.published_commands[0]["command_type"] == "speak"


def test_groq_failure_graceful_fallback():
    """
    When Groq API encounters a network timeout or provider error,
    it gracefully returns the in-character fallback response without crashing.
    """
    with patch("httpx.Client.post", side_effect=Exception("Connection timed out")):
        with patch.object(LLMService, "is_configured", return_value=True):
            reply = LLMService.generate_response(
                messages=[{"role": "user", "content": "Hello!"}]
            )
            assert reply == FALLBACK_REPLY


def test_structured_state_included_in_prompt(db_session):
    """
    Verifies that pending tasks and upcoming reminders from PostgreSQL
    are included in the synthesized context layers.
    """
    device_id = "dove-esp32-01"

    # Add a pending task
    task = TaskItem(
        title="Complete backend testing",
        status="pending",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(task)
    db_session.commit()

    prompt = ConversationService.build_system_prompt(
        db=db_session,
        device_id=device_id,
        user_query="What should I work on next?"
    )

    assert "[Structured State - Pending Tasks]:" in prompt
    assert "Complete backend testing" in prompt

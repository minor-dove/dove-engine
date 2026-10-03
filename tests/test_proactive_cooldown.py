"""
Proactive Cooldown and Preference Tests.
Verifies the 30-minute cooldown window, atomic reservation,
user-initiated bypass, and quiet hours constraints.
"""

from datetime import datetime, timezone, timedelta

from app.services.trigger_engine import TriggerEngine
from app.services.conversation_service import ConversationService
from app.schemas.mood import MoodEventCreate
from app.models.proactive import ProactiveCooldown
from app.models.preference import UserPreference


from app.core.security import ensure_utc


def test_cooldown_blocks_second_proactive_trigger(db_session):
    """
    After a proactive check-in is accepted, subsequent proactive triggers are blocked
    until the 30-minute cooldown expires.
    """
    device_id = "dove-esp32-01"
    base_time = datetime.now(timezone.utc) - timedelta(minutes=25)

    # 1. Trigger first proactive check-in with 10 Sad events
    for i in range(1, 11):
        res = TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"cd-sad-{i}",
            device_id=device_id,
            mood_id=4,
            recorded_at=base_time + timedelta(minutes=i)
        ))
    assert res["trigger_outcome"]["action"] == "initiated"

    # Verify cooldown was reserved in DB
    cooldown = db_session.query(ProactiveCooldown).filter(ProactiveCooldown.device_id == device_id).first()
    assert cooldown.cooldown_until is not None
    assert ensure_utc(cooldown.cooldown_until) > datetime.now(timezone.utc)

    # Close the conversation session to isolate cooldown testing
    from app.models.conversation import ConversationSession
    session = db_session.query(ConversationSession).filter(ConversationSession.device_id == device_id).first()
    session.is_active = False
    db_session.commit()

    # Reset streak by sending a neutral event, then 10 Angry events while still in cooldown
    TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
        event_id="cd-neutral-break",
        device_id=device_id,
        mood_id=6,
        recorded_at=datetime.now(timezone.utc) - timedelta(minutes=11)
    ))

    cd_base = datetime.now(timezone.utc) - timedelta(minutes=10)
    for j in range(1, 11):
        res2 = TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"cd-angry-{j}",
            device_id=device_id,
            mood_id=0,
            recorded_at=cd_base + timedelta(seconds=j * 30)
        ))

    # The 10th angry event should be skipped due to cooldown
    assert res2["trigger_outcome"]["action"] == "skipped"
    assert res2["trigger_outcome"]["reason"] == "cooldown_active"


def test_user_initiated_conversation_bypasses_cooldown(db_session):
    """
    User-initiated conversations must remain available regardless of proactive cooldown.
    """
    device_id = "dove-esp32-01"
    now = datetime.now(timezone.utc)

    # Lock proactive cooldown for the next 25 minutes
    cooldown = ProactiveCooldown(
        device_id=device_id,
        last_proactive_at=now,
        cooldown_until=now + timedelta(minutes=25),
        last_trigger_type="mood_sad"
    )
    db_session.add(cooldown)
    db_session.commit()

    # User initiates conversation
    response = ConversationService.handle_user_message(
        db=db_session,
        device_id=device_id,
        message_text="Hello Dove, are you there?"
    )

    assert response.session_id is not None
    assert response.reply is not None
    assert response.trigger_type == "user_initiated"


def test_proactive_disabled_by_preference(db_session):
    """
    When user sets proactive_enabled=False in preferences, proactive triggers are skipped.
    """
    device_id = "dove-esp32-01"
    pref = db_session.query(UserPreference).filter(UserPreference.id == 1).first()
    pref.proactive_enabled = False
    db_session.commit()

    base_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    for i in range(1, 11):
        res = TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"pref-sad-{i}",
            device_id=device_id,
            mood_id=4,
            recorded_at=base_time + timedelta(minutes=i)
        ))

    assert res["trigger_outcome"]["action"] == "skipped"
    assert res["trigger_outcome"]["reason"] == "proactive_disabled_by_user"

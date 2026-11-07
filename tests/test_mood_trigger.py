"""
Mood Ingestion & Deterministic Trigger Engine Tests.
Validates the exact 10-consecutive Angry/Sad rules, streak resets,
duplicate event handling, out-of-order rejection, and time-gap handling.
"""

from datetime import datetime, timezone, timedelta
from app.services.trigger_engine import TriggerEngine
from app.schemas.mood import MoodEventCreate
from app.models.mood import MoodEvent, MoodStreak
from app.models.conversation import ConversationSession


def test_ten_consecutive_sad_triggers_checkin(db_session):
    """
    10 consecutive Sad (mood_id=4) events qualify and initiate a proactive check-in.
    """
    base_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    device_id = "dove-esp32-01"

    for i in range(1, 10):
        event = MoodEventCreate(
            event_id=f"sad-evt-{i}",
            device_id=device_id,
            mood_id=4,  # Sad
            recorded_at=base_time + timedelta(minutes=i)
        )
        res = TriggerEngine.ingest_mood_event(db_session, event)
        assert res["status"] == "processed"
        assert res["streak"]["count"] == i
        assert res["trigger_outcome"]["action"] == "accumulating"

    # 10th consecutive Sad event qualifies!
    event_10 = MoodEventCreate(
        event_id="sad-evt-10",
        device_id=device_id,
        mood_id=4,
        recorded_at=base_time + timedelta(minutes=10)
    )
    res_10 = TriggerEngine.ingest_mood_event(db_session, event_10)
    assert res_10["status"] == "processed"
    assert res_10["streak"]["count"] == 10
    assert res_10["trigger_outcome"]["action"] == "initiated"
    assert "session_id" in res_10["trigger_outcome"]
    assert res_10["trigger_outcome"]["trigger_type"] == "mood_sad"


def test_ten_consecutive_angry_triggers_checkin(db_session):
    """
    10 consecutive Angry (mood_id=0) events qualify and initiate a proactive check-in.
    """
    base_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    device_id = "dove-esp32-01"

    for i in range(1, 10):
        event = MoodEventCreate(
            event_id=f"angry-evt-{i}",
            device_id=device_id,
            mood_id=0,  # Angry
            recorded_at=base_time + timedelta(minutes=i)
        )
        res = TriggerEngine.ingest_mood_event(db_session, event)
        assert res["streak"]["count"] == i

    # 10th Angry qualifies
    event_10 = MoodEventCreate(
        event_id="angry-evt-10",
        device_id=device_id,
        mood_id=0,
        recorded_at=base_time + timedelta(minutes=10)
    )
    res_10 = TriggerEngine.ingest_mood_event(db_session, event_10)
    assert res_10["trigger_outcome"]["action"] == "initiated"
    assert res_10["trigger_outcome"]["trigger_type"] == "mood_angry"


def test_five_angry_followed_by_five_sad_does_not_qualify(db_session):
    """
    5 Angry inputs followed by 5 Sad inputs do not qualify.
    Alternating resets the opposing streak.
    """
    base_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    device_id = "dove-esp32-01"

    # Send 5 Angry
    for i in range(1, 6):
        event = MoodEventCreate(
            event_id=f"mixed-angry-{i}",
            device_id=device_id,
            mood_id=0,
            recorded_at=base_time + timedelta(minutes=i)
        )
        res = TriggerEngine.ingest_mood_event(db_session, event)
        assert res["streak"]["count"] == i

    # Send 5 Sad (should reset Angry count to 0, start Sad count at 1..5)
    for j in range(1, 6):
        event = MoodEventCreate(
            event_id=f"mixed-sad-{j}",
            device_id=device_id,
            mood_id=4,
            recorded_at=base_time + timedelta(minutes=5 + j)
        )
        res = TriggerEngine.ingest_mood_event(db_session, event)
        assert res["streak"]["count"] == j
        assert res["trigger_outcome"]["action"] == "accumulating"

    # Verify Angry streak was reset to 0 in DB
    angry_streak = db_session.query(MoodStreak).filter(
        MoodStreak.device_id == device_id, MoodStreak.mood_id == 0
    ).first()
    assert angry_streak.current_count == 0


def test_neutral_or_happy_resets_streak(db_session):
    """
    Receiving Neutral (6) or Happy (3) completely resets both Angry and Sad streaks.
    """
    base_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    device_id = "dove-esp32-01"

    # Send 8 Angry events
    for i in range(1, 9):
        TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"res-angry-{i}",
            device_id=device_id,
            mood_id=0,
            recorded_at=base_time + timedelta(minutes=i)
        ))

    # Send Neutral (6)
    neutral_res = TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
        event_id="res-neutral-1",
        device_id=device_id,
        mood_id=6,
        recorded_at=base_time + timedelta(minutes=9)
    ))

    assert neutral_res["streak"]["count"] == 0

    # Next Angry event starts at count 1
    next_angry = TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
        event_id="res-angry-new-1",
        device_id=device_id,
        mood_id=0,
        recorded_at=base_time + timedelta(minutes=10)
    ))
    assert next_angry["streak"]["count"] == 1


def test_missing_observation_gap_resets_streak(db_session):
    """
    Missing observations (> 150 seconds gap) interrupts continuity and resets streak to 1.
    """
    base_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    device_id = "dove-esp32-01"

    # Send 5 Sad events (1 min apart)
    for i in range(1, 6):
        TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"gap-sad-{i}",
            device_id=device_id,
            mood_id=4,
            recorded_at=base_time + timedelta(minutes=i)
        ))

    # Gap of 5 minutes (> 150 seconds threshold)
    gap_event = MoodEventCreate(
        event_id="gap-sad-after-gap",
        device_id=device_id,
        mood_id=4,
        recorded_at=base_time + timedelta(minutes=11)
    )
    res = TriggerEngine.ingest_mood_event(db_session, gap_event)
    assert res["streak"]["gap_broken"] is True
    assert res["streak"]["count"] == 1


def test_duplicate_event_id_is_rejected(db_session):
    """
    Duplicate event_id is safely ignored and does not advance streak count.
    """
    now = datetime.now(timezone.utc)
    device_id = "dove-esp32-01"

    event1 = MoodEventCreate(
        event_id="dup-evt-001",
        device_id=device_id,
        mood_id=0,
        recorded_at=now - timedelta(minutes=2)
    )
    res1 = TriggerEngine.ingest_mood_event(db_session, event1)
    assert res1["status"] == "processed"
    assert res1["streak"]["count"] == 1

    # Same event_id resent
    res2 = TriggerEngine.ingest_mood_event(db_session, event1)
    assert res2["status"] == "duplicate"

    # Verify streak count did not advance
    streak = db_session.query(MoodStreak).filter(
        MoodStreak.device_id == device_id, MoodStreak.mood_id == 0
    ).first()
    assert streak.current_count == 1


def test_stale_or_future_event_is_ignored(db_session):
    """
    Events older than 5 minutes or in the future beyond clock skew are ignored.
    """
    now = datetime.now(timezone.utc)
    device_id = "dove-esp32-01"

    # Stale: 40 minutes ago (> 30 minute freshness window)
    stale_event = MoodEventCreate(
        event_id="stale-001",
        device_id=device_id,
        mood_id=0,
        recorded_at=now - timedelta(minutes=40)
    )
    res_stale = TriggerEngine.ingest_mood_event(db_session, stale_event)
    assert res_stale["status"] == "ignored"
    assert res_stale["reason"] == "stale_or_future_timestamp"

    # Future: 5 minutes in future
    future_event = MoodEventCreate(
        event_id="future-001",
        device_id=device_id,
        mood_id=0,
        recorded_at=now + timedelta(minutes=5)
    )
    res_future = TriggerEngine.ingest_mood_event(db_session, future_event)
    assert res_future["status"] == "ignored"
    assert res_future["reason"] == "stale_or_future_timestamp"


def test_prevent_repeated_checkin_while_qualifying_mood_persists(db_session):
    """
    Subsequent 11th, 12th events of same mood do not trigger repeated conversations.
    Requires a new qualifying streak.
    """
    base_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    device_id = "dove-esp32-01"

    for i in range(1, 11):
        TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"repeat-sad-{i}",
            device_id=device_id,
            mood_id=4,
            recorded_at=base_time + timedelta(minutes=i)
        ))

    # 11th event of the same continuing Sad streak
    event_11 = MoodEventCreate(
        event_id="repeat-sad-11",
        device_id=device_id,
        mood_id=4,
        recorded_at=base_time + timedelta(minutes=11)
    )
    res_11 = TriggerEngine.ingest_mood_event(db_session, event_11)
    # Action should be skipped because qualifying streak already triggered
    assert res_11["trigger_outcome"]["action"] == "skipped"


def test_active_conversation_uses_mood_as_context(db_session):
    """
    If a conversation is already active, incoming qualifying mood does not open a duplicate session.
    """
    device_id = "dove-esp32-01"
    now = datetime.now(timezone.utc)

    # Create active session
    active_session = ConversationSession(
        device_id=device_id,
        is_active=True,
        trigger_type="user_initiated",
        started_at=now
    )
    db_session.add(active_session)
    db_session.commit()

    base_time = now - timedelta(minutes=15)
    for i in range(1, 11):
        res = TriggerEngine.ingest_mood_event(db_session, MoodEventCreate(
            event_id=f"active-sess-angry-{i}",
            device_id=device_id,
            mood_id=0,
            recorded_at=base_time + timedelta(minutes=i)
        ))

    # 10th should skip opening duplicate session
    assert res["trigger_outcome"]["action"] == "skipped"
    assert res["trigger_outcome"]["reason"] == "conversation_already_active"

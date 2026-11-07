"""Emotion ingestion is signal-only: store, dedupe, reject stale, honour privacy. No triggers."""

from datetime import datetime, timedelta, timezone
from app.models.conversation import ConversationSession
from app.models.mood import MoodEvent
from app.schemas.mood import MoodEventCreate
from app.services.device_state_service import DeviceStateService
from app.services.trigger_engine import TriggerEngine

DEV = "dove-esp32-01"


def ev(eid, mood=4, at=None):
    return MoodEventCreate(event_id=eid, device_id=DEV, mood_id=mood, recorded_at=at or datetime.now(timezone.utc))


def test_ingest_stores_and_marks_present(db_session):
    r = TriggerEngine.ingest_mood_event(db_session, ev("a1"))
    assert r["status"] == "processed" and r["emotion"] == "Sad"
    assert db_session.query(MoodEvent).count() == 1
    assert DeviceStateService.present_for_seconds(db_session, DEV, datetime.now(timezone.utc)) >= 0
    assert DeviceStateService._get_or_create(db_session, DEV).present is True


def test_many_sad_events_never_start_a_conversation(db_session):
    base = datetime.now(timezone.utc) - timedelta(minutes=15)
    for i in range(12):
        r = TriggerEngine.ingest_mood_event(db_session, ev(f"s{i}", 4, base + timedelta(minutes=i)))
        assert "trigger_outcome" not in r
    assert db_session.query(ConversationSession).count() == 0


def test_duplicate_and_stale_rejected(db_session):
    TriggerEngine.ingest_mood_event(db_session, ev("d1"))
    assert TriggerEngine.ingest_mood_event(db_session, ev("d1"))["status"] == "duplicate"
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    assert TriggerEngine.ingest_mood_event(db_session, ev("old", at=old))["status"] == "ignored"


def test_events_dropped_in_privacy_mode(db_session):
    DeviceStateService.set_privacy(db_session, DEV, True)
    r = TriggerEngine.ingest_mood_event(db_session, ev("p1"))
    assert r["reason"] == "privacy_mode" and db_session.query(MoodEvent).count() == 0


def test_first_event_from_unknown_device_creates_device_and_state(db_session):
    e = MoodEventCreate(event_id="new1", device_id="brand-new", mood_id=3, recorded_at=datetime.now(timezone.utc))
    assert TriggerEngine.ingest_mood_event(db_session, e)["status"] == "processed"
    assert DeviceStateService.present_for_seconds(db_session, "brand-new", datetime.now(timezone.utc) + timedelta(seconds=5)) > 0

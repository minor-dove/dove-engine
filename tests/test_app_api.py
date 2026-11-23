"""Companion-app read endpoints: history, daily trend, transcript, device status, mood summary, deletes."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.device_state import DeviceState
from app.models.mood import MoodEvent
from app.models.stress import StressSession
from app.services import stress_service
from app.services.stress_service import StressService

DEV = "dove-esp32-01"


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)


def _complete(db, answer="a little"):
    sid = StressService.start_session(db, DEV)["session_id"]
    for _ in range(5):
        StressService.submit_answer(db, sid, answer)
    return sid


def test_sessions_list_empty_is_not_faked(client):
    r = client.get("/api/v1/stress/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0 and body["sessions"] == [] and "not a medical" in body["disclaimer"]


def test_sessions_list_and_filters(client, db_session):
    done = _complete(db_session, "very often")
    StressService.start_session(db_session, DEV)  # stays active
    body = client.get("/api/v1/stress/sessions").json()
    assert body["total"] == 2
    by_id = {s["session_id"]: s for s in body["sessions"]}
    assert by_id[done]["status"] == "completed" and by_id[done]["score"] is not None
    assert by_id[done]["band"] and by_id[done]["preview"] and by_id[done]["message_count"] >= 2
    active = [s for s in body["sessions"] if s["status"] == "active"]
    assert len(active) == 1 and active[0]["score"] is None
    assert client.get("/api/v1/stress/sessions?status=completed").json()["total"] == 1
    assert client.get("/api/v1/stress/sessions?status=bogus").status_code == 422
    assert client.get("/api/v1/stress/sessions?limit=1").json()["sessions"].__len__() == 1
    assert client.get("/api/v1/stress/sessions?day=2000-01-01").json()["total"] == 0


def test_transcript_and_delete(client, db_session):
    sid = _complete(db_session)
    t = client.get(f"/api/v1/stress/sessions/{sid}/transcript").json()
    assert t["session"]["session_id"] == sid
    roles = [m["role"] for m in t["messages"]]
    assert roles[0] == "assistant" and "user" in roles
    assert client.get("/api/v1/stress/sessions/nope/transcript").status_code == 404

    assert client.delete(f"/api/v1/stress/sessions/{sid}").status_code == 204
    assert client.get(f"/api/v1/stress/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/v1/stress/sessions/{sid}").status_code == 404
    assert client.get("/api/v1/stress/sessions").json()["total"] == 0


def test_day_history_range_and_trend(client, db_session):
    _complete(db_session, "very often")
    today = StressService.local_today(db_session)
    # a completed session two days ago with a known lower score
    old = db_session.query(StressSession).first()
    prev = StressSession(device_id=DEV, local_date=today - timedelta(days=9), status="completed",
                         item_plan="[1,2,3]", score=10.0)
    db_session.add(prev)
    db_session.commit()

    body = client.get("/api/v1/stress/days?days=7").json()
    assert len(body["days"]) == 7 and body["today"] == today.isoformat()
    assert body["days"][-1]["date"] == today.isoformat() and body["days"][-1]["status"] == "ok"
    assert all(d["status"] == "no_data" and d["day_score"] is None for d in body["days"][:-1])
    assert body["average_score"] == old.score
    assert body["previous_average_score"] == 10.0
    assert body["trend"] == "up"
    assert client.get("/api/v1/stress/days?days=0").status_code == 422
    assert client.get("/api/v1/stress/days?days=91").status_code == 422


def test_day_history_empty(client):
    body = client.get("/api/v1/stress/days?days=3").json()
    assert body["average_score"] is None and body["trend"] is None
    assert [d["status"] for d in body["days"]] == ["no_data"] * 3


def test_device_status(client, db_session):
    s = client.get(f"/api/v1/devices/{DEV}/status").json()
    assert s["registered"] is True and s["privacy_on"] is False and s["active_session"] is None
    assert s["completed_today"] == 0

    ghost = client.get("/api/v1/devices/ghost/status").json()
    assert ghost["registered"] is False and ghost["connection"] == "unknown"

    from app.services.device_state_service import DeviceStateService
    DeviceStateService.set_privacy(db_session, DEV, True)
    assert client.get(f"/api/v1/devices/{DEV}/status").json()["privacy_on"] is True
    DeviceStateService.set_privacy(db_session, DEV, False)

    StressService.start_session(db_session, DEV)
    act = client.get(f"/api/v1/devices/{DEV}/status").json()["active_session"]
    assert act["answered"] == 0 and act["total"] == 3


def test_device_connection_freshness(db_session):
    from app.models.device import Device
    from app.services.app_overview_service import AppOverviewService
    now = datetime.now(timezone.utc)
    d = db_session.query(Device).filter(Device.id == DEV).first()
    d.status, d.last_seen_at = "online", now - timedelta(seconds=30)
    db_session.commit()
    assert AppOverviewService.device_status(db_session, DEV, now)["connection"] == "online"
    d.last_seen_at = now - timedelta(minutes=30)
    db_session.commit()
    assert AppOverviewService.device_status(db_session, DEV, now)["connection"] == "offline"
    d.status, d.last_seen_at = "offline", now
    db_session.commit()
    assert AppOverviewService.device_status(db_session, DEV, now)["connection"] == "offline"


def test_mood_summary_and_delete(client, db_session):
    now = datetime.now(timezone.utc)
    for i, mid in enumerate([3, 3, 4, 6]):
        db_session.add(MoodEvent(event_id=f"m{i}", device_id=DEV, mood_id=mid,
                                 emotion={3: "Happy", 4: "Sad", 6: "Neutral"}[mid], recorded_at=now))
    db_session.add(MoodEvent(event_id="old", device_id=DEV, mood_id=3, emotion="Happy",
                             recorded_at=now - timedelta(days=20)))
    db_session.commit()
    d = client.get(f"/api/v1/mood/summary/{DEV}?period=today").json()
    assert d["total"] == 4 and d["counts"] == {"Happy": 2, "Sad": 1, "Neutral": 1}
    assert sum(b["total"] for b in d["buckets"]) == 4
    assert client.get(f"/api/v1/mood/summary/{DEV}?period=week").json()["total"] == 4
    assert client.get(f"/api/v1/mood/summary/{DEV}?period=month").json()["total"] == 5
    assert client.get(f"/api/v1/mood/summary/{DEV}?period=year").status_code == 422
    assert client.get("/api/v1/mood/summary/nobody").json()["total"] == 0

    assert client.delete(f"/api/v1/mood/events/{DEV}").json()["deleted"] == 5
    assert client.get(f"/api/v1/mood/summary/{DEV}?period=month").json()["total"] == 0


def test_emotion_data_never_changes_history_scores(client, db_session):
    a = _complete(db_session, "a little")
    score_before = client.get(f"/api/v1/stress/sessions/{a}/transcript").json()["session"]["score"]
    now = datetime.now(timezone.utc)
    for i in range(10):
        db_session.add(MoodEvent(event_id=f"x{i}", device_id=DEV, mood_id=4, emotion="Sad", recorded_at=now))
    db_session.commit()
    assert client.get(f"/api/v1/stress/sessions/{a}/transcript").json()["session"]["score"] == score_before

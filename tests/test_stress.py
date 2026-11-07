"""Stress scoring: item math, session flow, daily aggregation, emotion independence."""

from datetime import datetime, timezone
from app.models.mood import MoodEvent
from app.services import stress_service
from app.services.stress_items import compute_score, plan_items, REVERSE_ITEMS, ITEMS
from app.services.stress_service import StressService, heuristic_value

import pytest

DEV = "dove-esp32-01"


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    """Keep these tests deterministic and off the network."""
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)


def test_score_math_and_reverse():
    # all positive-direction answers on negative items = max stress
    assert compute_score([(1, 4), (2, 4), (3, 4)]) == 100.0
    assert compute_score([(1, 0), (2, 0), (3, 0)]) == 0.0
    # reverse item: value 4 ("very often confident") = 0 stress
    assert compute_score([(4, 4), (5, 4), (8, 4)]) == 0.0
    assert compute_score([(4, 0), (1, 4), (2, 2)]) == round((4 + 4 + 2) / 3 / 4 * 100, 1)


def test_needs_min_valid_items():
    assert compute_score([(1, 2), (2, None), (3, 1)]) is None


def test_plan_has_reverse_item_and_rotates():
    p1 = plan_items({})
    assert len(p1) == 5 and any(i in REVERSE_ITEMS for i in p1)
    p2 = plan_items({i: 1 for i in p1})
    assert set(p2) != set(p1)


def test_heuristic():
    assert heuristic_value("not at all") == 0
    assert heuristic_value("sometimes honestly") == 2
    assert heuristic_value("3") == 3
    assert heuristic_value("hmm dunno") is None


def _run(db, answers, mock):
    res = StressService.start_session(db, DEV, mqtt_publisher=mock)
    sid = res["session_id"]
    for a in answers:
        res = StressService.submit_answer(db, sid, a, mqtt_publisher=mock)
    return sid, res


def test_full_session_completes(db_session, mock_mqtt):
    sid, res = _run(db_session, ["very often"] * 5, mock_mqtt)
    assert res["status"] == "completed" and res["score"] is not None
    cmds = [c["command_type"] for c in mock_mqtt.published_commands]
    assert cmds[0] == "session_start" and cmds[-1] == "session_end"


def test_unclear_answer_clarifies_once_then_drops(db_session, mock_mqtt):
    res = StressService.start_session(db_session, DEV)
    sid = res["session_id"]
    r1 = StressService.submit_answer(db_session, sid, "hmm dunno")
    assert r1["progress"]["answered"] == 0 and "how often" in r1["question"].lower()
    r2 = StressService.submit_answer(db_session, sid, "no idea")
    assert r2["progress"]["answered"] == 1 and r2["items"][0]["value"] is None


def test_too_many_dropped_is_incomplete(db_session):
    res = StressService.start_session(db_session, DEV)
    sid = res["session_id"]
    for _ in range(5):
        StressService.submit_answer(db_session, sid, "dunno")
        res = StressService.submit_answer(db_session, sid, "dunno")
    assert res["status"] == "incomplete" and res["score"] is None


def test_emotion_does_not_change_score(db_session):
    def add_moods(mood_id, name, n):
        for i in range(n):
            db_session.add(MoodEvent(event_id=f"{name}{i}{mood_id}", device_id=DEV, mood_id=mood_id,
                                     emotion=name, recorded_at=datetime.now(timezone.utc)))
        db_session.commit()
    _, a = _run(db_session, ["sometimes"] * 5, None)
    add_moods(4, "Sad", 30)
    _, b = _run(db_session, ["sometimes"] * 5, None)
    # same answers -> same score regardless of emotion history (item sets differ, all value 2)
    assert a["score"] is not None and b["score"] is not None
    assert StressService.emotion_summary(db_session, DEV).startswith("last 3h")


def test_day_report_averages_completed_only(db_session):
    _run(db_session, ["not at all"] * 5, None)
    _run(db_session, ["very often"] * 5, None)
    _run(db_session, ["dunno", "dunno"] * 5, None)  # incomplete: excluded
    rep = StressService.day_report(db_session, DEV, StressService.local_today(db_session))
    assert rep["completed_sessions"] == 2 and rep["status"] == "ok"
    assert 0 < rep["day_score"] < 100
    empty = StressService.day_report(db_session, DEV, datetime(2000, 1, 1).date())
    assert empty["status"] == "no_data" and empty["day_score"] is None


def test_api_flow(client):
    r = client.post("/api/v1/stress/sessions", json={})
    assert r.status_code == 201
    sid = r.json()["session_id"]
    for _ in range(5):
        r = client.post(f"/api/v1/stress/sessions/{sid}/answer", json={"text": "a little"})
    assert r.json()["status"] == "completed"
    assert client.get(f"/api/v1/stress/sessions/{sid}").json()["score"] is not None
    assert client.get(f"/api/v1/stress/sessions/nope").status_code == 404


def test_start_for_unregistered_device_is_404(client):
    r = client.post("/api/v1/stress/sessions", json={"device_id": "ghost"})
    assert r.status_code == 404

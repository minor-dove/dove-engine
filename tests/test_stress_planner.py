"""Presence-based planner: decision rules, catch-up, privacy abort, idle expiry, MQTT handlers."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.mqtt.handlers import handle_incoming_presence, handle_incoming_privacy
from app.models.preference import UserPreference
from app.models.stress import StressSession
from app.services import stress_service
from app.services.device_state_service import DeviceStateService
from app.services.stress_planner import StressPlanner, decide
from app.services.stress_service import StressService

DEV = "dove-esp32-01"
TZ = ZoneInfo("Asia/Kolkata")


def at(h, m=0, day=7):
    return datetime(2026, 11, day, h, m, tzinfo=TZ)


def kw(**o):
    base = dict(now_local=at(10), completed_ends=[], last_attempt_at=None, last_attempt_completed=False,
                has_active=False, privacy_on=False, present_seconds=300, quiet=False)
    base.update(o)
    return base


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)


# ---------- pure decision rules ----------
def test_starts_when_present_and_in_window():
    assert decide(**kw()) == (True, "scheduled")


@pytest.mark.parametrize("override,reason", [
    (dict(privacy_on=True), "privacy_mode"),
    (dict(quiet=True), "quiet_hours"),
    (dict(present_seconds=10), "not_present"),
    (dict(has_active=True), "active_session"),
    (dict(now_local=at(8)), "outside_day_window"),
    (dict(now_local=at(21, 30)), "outside_day_window"),
])
def test_blockers(override, reason):
    assert decide(**kw(**override)) == (False, reason)


def test_quota_met():
    ends = [at(9, 30), at(13, 5), at(17, 10)]
    assert decide(**kw(now_local=at(19), completed_ends=ends)) == (False, "quota_met")


def test_second_session_waits_for_slot_and_gap():
    assert decide(**kw(now_local=at(11), completed_ends=[at(9, 5)]))[1] == "before_slot"
    # slot 2 opens 13:00; gap satisfied
    assert decide(**kw(now_local=at(13, 10), completed_ends=[at(9, 5)])) == (True, "scheduled")
    # slot open but too soon after the previous completion
    assert decide(**kw(now_local=at(13, 10), completed_ends=[at(12, 30)]))[1] == "min_gap"


def test_catchup_when_day_running_out():
    # 18:30 with 0 done: 2.5h left < 3 sessions*2h -> catch-up, not blocked by slots
    assert decide(**kw(now_local=at(18, 30))) == (True, "catchup")
    # catch-up still honours the short gap
    assert decide(**kw(now_local=at(18, 30), completed_ends=[at(18, 20)]))[1] == "min_gap"


def test_retry_wait_after_unfinished_attempt():
    r = decide(**kw(last_attempt_at=at(9, 55), now_local=at(10, 0)))
    assert r == (False, "retry_wait")
    assert decide(**kw(last_attempt_at=at(9, 40), now_local=at(10, 0))) == (True, "scheduled")


# ---------- integration ----------
def now_utc(h, m=0):
    return at(h, m).astimezone(timezone.utc)


def test_planner_starts_session_only_when_present(db_session, mock_mqtt):
    DeviceStateService.set_presence(db_session, DEV, False)
    assert StressPlanner.run(db_session, now=now_utc(10), mqtt_publisher=mock_mqtt) == []
    DeviceStateService.set_presence(db_session, DEV, True, now=now_utc(9, 55))
    assert StressPlanner.run(db_session, now=now_utc(10), mqtt_publisher=mock_mqtt) == [DEV]
    assert mock_mqtt.published_commands[0]["command_type"] == "session_start"
    # active session blocks a second one
    assert StressPlanner.run(db_session, now=now_utc(10, 1), mqtt_publisher=mock_mqtt) == []


def test_privacy_on_aborts_active_session_and_blocks(db_session, mock_mqtt):
    DeviceStateService.set_presence(db_session, DEV, True, now=now_utc(9, 55))
    StressPlanner.run(db_session, now=now_utc(10), mqtt_publisher=mock_mqtt)
    s = db_session.query(StressSession).one()
    DeviceStateService.set_privacy(db_session, DEV, True, now=now_utc(10, 2), mqtt_publisher=mock_mqtt)
    db_session.refresh(s)
    assert s.status == "aborted"
    assert mock_mqtt.published_commands[-1]["command_type"] == "session_end"
    DeviceStateService.set_presence(db_session, DEV, True, now=now_utc(10, 3))
    assert StressPlanner.run(db_session, now=now_utc(10, 30), mqtt_publisher=mock_mqtt) == []
    DeviceStateService.set_privacy(db_session, DEV, False, now=now_utc(10, 31))
    assert StressPlanner.run(db_session, now=now_utc(10, 50), mqtt_publisher=mock_mqtt) == [DEV]


def test_idle_session_expires(db_session, mock_mqtt):
    DeviceStateService.set_presence(db_session, DEV, True, now=now_utc(9, 55))
    StressPlanner.run(db_session, now=now_utc(10), mqtt_publisher=mock_mqtt)
    s = db_session.query(StressSession).one()
    assert StressPlanner.expire_idle_sessions(db_session, datetime.now(timezone.utc) + timedelta(minutes=30)) == 1
    db_session.refresh(s)
    assert s.status == "aborted"


def test_full_day_reaches_three_sessions(db_session):
    DeviceStateService.set_presence(db_session, DEV, True, now=now_utc(8, 0))
    done = 0
    for minute in range(9 * 60, 21 * 60, 5):
        n = now_utc(minute // 60, minute % 60)
        started = StressPlanner.run(db_session, now=n)
        if started:
            s = db_session.query(StressSession).filter_by(status="active").one()
            for _ in range(5):
                StressService.submit_answer(db_session, s.id, "sometimes")
            s.ended_at = n  # finish "now" in simulated time
            db_session.commit()
            done += 1
    assert done == 3
    from app.services.stress_service import StressService as SS
    rep = SS.day_report(db_session, DEV, at(10).date())
    assert rep["completed_sessions"] == 3 and rep["day_score"] is not None


def test_mqtt_presence_and_privacy_handlers(db_session, monkeypatch):
    class _Shared:  # route handler sessions to the test DB; ignore close()
        def __getattr__(self, n):
            return getattr(db_session, n)
        def close(self):
            pass
    monkeypatch.setattr("app.mqtt.handlers.SessionLocal", lambda: _Shared())
    t = f"dove/devices/{DEV}"
    assert handle_incoming_presence(f"{t}/presence", json.dumps({"present": True}).encode())["status"] == "updated"
    assert DeviceStateService._get_or_create(db_session, DEV).present is True
    assert handle_incoming_privacy(f"{t}/privacy", json.dumps({"mode": "on"}).encode())["privacy"] == "on"
    db_session.expire_all()
    assert DeviceStateService.is_privacy_on(db_session, DEV) is True
    assert handle_incoming_privacy(f"{t}/privacy", b'{"mode":"maybe"}')["status"] == "error"

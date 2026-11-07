"""
Presence-based stress session planner.

Goal: at least STRESS_DAILY_TARGET completed sessions per local day, started only when the
user is present (and settled), privacy is off, outside quiet hours and inside the day window.
Slots spread the sessions across the day; if time is running out the gaps shrink (catch-up).
The decision function is pure so it can be tested with a fixed clock.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import ensure_utc
from app.models.conversation import ConversationMessage
from app.models.device import Device
from app.models.preference import UserPreference
from app.models.stress import StressSession
from app.services.device_state_service import DeviceStateService
from app.services.stress_service import StressService
from app.services.trigger_engine import is_within_quiet_hours

logger = logging.getLogger(__name__)


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def slot_start_minute(k: int) -> int:
    start, end = _hhmm(settings.STRESS_DAY_START), _hhmm(settings.STRESS_DAY_END)
    return start + k * (end - start) // settings.STRESS_DAILY_TARGET


def decide(now_local: datetime, completed_ends: List[datetime], last_attempt_at: Optional[datetime],
           last_attempt_completed: bool, has_active: bool, privacy_on: bool,
           present_seconds: float, quiet: bool, proactive_enabled: bool = True) -> Tuple[bool, str]:
    """Returns (start_now, reason). All datetimes timezone-aware in the same tz."""
    k = len(completed_ends)
    if not proactive_enabled:
        return False, "disabled"
    if k >= settings.STRESS_DAILY_TARGET:
        return False, "quota_met"
    if has_active:
        return False, "active_session"
    if privacy_on:
        return False, "privacy_mode"
    if quiet:
        return False, "quiet_hours"
    minute = now_local.hour * 60 + now_local.minute
    day_start, day_end = _hhmm(settings.STRESS_DAY_START), _hhmm(settings.STRESS_DAY_END)
    if not (day_start <= minute < day_end):
        return False, "outside_day_window"

    remaining = settings.STRESS_DAILY_TARGET - k
    catchup = (day_end - minute) <= remaining * settings.STRESS_MIN_GAP_MINUTES
    if not catchup and minute < slot_start_minute(k):
        return False, "before_slot"
    gap = settings.STRESS_CATCHUP_GAP_MINUTES if catchup else settings.STRESS_MIN_GAP_MINUTES
    if completed_ends and now_local - max(completed_ends) < timedelta(minutes=gap):
        return False, "min_gap"
    if last_attempt_at and not last_attempt_completed and \
            now_local - last_attempt_at < timedelta(minutes=settings.STRESS_RETRY_MINUTES):
        return False, "retry_wait"
    if present_seconds <= 0 or present_seconds < settings.STRESS_PRESENCE_SETTLE_SECONDS:
        return False, "not_present"
    return True, "catchup" if catchup else "scheduled"


class StressPlanner:

    @staticmethod
    def expire_idle_sessions(db: Session, now: datetime, mqtt_publisher: Optional[Any] = None) -> int:
        n = 0
        timeout = timedelta(minutes=settings.STRESS_SESSION_TIMEOUT_MINUTES)
        for s in db.query(StressSession).filter(StressSession.status == "active").all():
            last = db.query(ConversationMessage.created_at).filter(
                ConversationMessage.session_id == s.conversation_session_id
            ).order_by(ConversationMessage.created_at.desc()).first()
            last_at = ensure_utc(last[0]) if last else ensure_utc(s.started_at)
            if now - last_at > timeout:
                StressService.abort_session(db, s.id, mqtt_publisher=mqtt_publisher)
                n += 1
        return n

    @staticmethod
    def run_for_device(db: Session, device_id: str, now: Optional[datetime] = None,
                       mqtt_publisher: Optional[Any] = None) -> Tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
        try:
            tz = ZoneInfo(pref.timezone) if pref else timezone.utc
        except Exception:
            tz = timezone.utc
        now_local = now.astimezone(tz)
        today = now_local.date()

        todays = db.query(StressSession).filter(
            StressSession.device_id == device_id, StressSession.local_date == today
        ).order_by(StressSession.started_at).all()
        completed_ends = [ensure_utc(x.ended_at).astimezone(tz) for x in todays
                          if x.status == "completed" and x.ended_at]
        last = todays[-1] if todays else None
        quiet = bool(pref) and is_within_quiet_hours(now, pref.quiet_hours_start, pref.quiet_hours_end, pref.timezone)

        go, reason = decide(
            now_local=now_local,
            completed_ends=completed_ends,
            last_attempt_at=ensure_utc(last.started_at).astimezone(tz) if last else None,
            last_attempt_completed=bool(last and last.status == "completed"),
            has_active=any(x.status == "active" for x in todays),
            privacy_on=DeviceStateService.is_privacy_on(db, device_id),
            present_seconds=DeviceStateService.present_for_seconds(db, device_id, now),
            quiet=quiet,
            proactive_enabled=bool(pref.proactive_enabled) if pref else True,
        )
        if go:
            StressService.start_session(db, device_id, mqtt_publisher=mqtt_publisher, now=now)
            logger.info(f"Started stress session for {device_id} ({reason})")
        return go, reason

    @staticmethod
    def run(db: Session, now: Optional[datetime] = None, mqtt_publisher: Optional[Any] = None) -> List[str]:
        now = now or datetime.now(timezone.utc)
        StressPlanner.expire_idle_sessions(db, now, mqtt_publisher)
        started = []
        for (device_id,) in db.query(Device.id).all():
            go, _ = StressPlanner.run_for_device(db, device_id, now, mqtt_publisher)
            if go:
                started.append(device_id)
        return started

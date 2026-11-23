"""
Read-side aggregation for the companion app: session history, daily trend, device status, mood summary.
Pure queries: nothing here writes scores, and emotion data is never combined with scores.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.security import ensure_utc
from app.models.conversation import ConversationMessage
from app.models.device import Device
from app.models.device_state import DeviceState
from app.models.mood import MoodEvent
from app.models.preference import UserPreference
from app.models.stress import StressSession
from app.services.stress_items import band_for
from app.services.stress_service import DISCLAIMER, StressService

ONLINE_WINDOW_S = 180  # firmware heartbeats every 60 s
PERIOD_DAYS = {"today": 1, "week": 7, "month": 30}


def user_tz(db: Session):
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    try:
        return ZoneInfo(pref.timezone) if pref else timezone.utc
    except Exception:
        return timezone.utc


def _summary(db: Session, s: StressSession) -> Dict[str, Any]:
    plan = StressService._plan(s)
    first = None
    count = 0
    if s.conversation_session_id:
        msgs = db.query(ConversationMessage).filter(
            ConversationMessage.session_id == s.conversation_session_id).order_by(ConversationMessage.id).all()
        count = len(msgs)
        first = next((m.content for m in msgs if m.role == "assistant"), None)
    return {
        "session_id": s.id, "device_id": s.device_id, "status": s.status, "local_date": s.local_date,
        "started_at": s.started_at, "ended_at": s.ended_at, "daypart": s.daypart, "score": s.score,
        "band": band_for(s.score) if s.score is not None else None,
        "answered": len(s.responses), "total": len(plan), "summary": s.summary,
        "preview": first, "message_count": count,
    }


class AppOverviewService:

    @staticmethod
    def list_sessions(db: Session, device_id: str, limit: int = 50, offset: int = 0,
                      day: Optional[date] = None, status: Optional[str] = None) -> Dict[str, Any]:
        q = db.query(StressSession).filter(StressSession.device_id == device_id)
        if day:
            q = q.filter(StressSession.local_date == day)
        if status:
            q = q.filter(StressSession.status == status)
        total = q.count()
        rows = q.order_by(StressSession.started_at.desc()).offset(offset).limit(limit).all()
        return {"device_id": device_id, "total": total,
                "sessions": [_summary(db, s) for s in rows], "disclaimer": DISCLAIMER}

    @staticmethod
    def transcript(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
        s = db.query(StressSession).filter(StressSession.id == session_id).first()
        if not s:
            return None
        msgs = []
        if s.conversation_session_id:
            msgs = db.query(ConversationMessage).filter(
                ConversationMessage.session_id == s.conversation_session_id,
                ConversationMessage.role.in_(("user", "assistant"))).order_by(ConversationMessage.id).all()
        return {"session": _summary(db, s), "messages": msgs, "disclaimer": DISCLAIMER}

    @staticmethod
    def delete_session(db: Session, session_id: str) -> bool:
        from app.models.conversation import ConversationSession
        s = db.query(StressSession).filter(StressSession.id == session_id).first()
        if not s:
            return False
        conv_id = s.conversation_session_id
        db.delete(s)
        if conv_id:
            conv = db.query(ConversationSession).filter(ConversationSession.id == conv_id).first()
            if conv:
                db.delete(conv)  # cascades messages and memories derived from this conversation
        db.commit()
        return True

    @staticmethod
    def _range_scores(db: Session, device_id: str, start: date, end: date) -> Dict[date, List[float]]:
        rows = db.query(StressSession.local_date, StressSession.score).filter(
            StressSession.device_id == device_id, StressSession.status == "completed",
            StressSession.score.isnot(None), StressSession.local_date >= start,
            StressSession.local_date <= end).all()
        out: Dict[date, List[float]] = defaultdict(list)
        for d, sc in rows:
            out[d].append(sc)
        return out

    @staticmethod
    def day_history(db: Session, device_id: str, days: int = 7, end: Optional[date] = None) -> Dict[str, Any]:
        today = StressService.local_today(db)
        end = end or today
        start = end - timedelta(days=days - 1)
        cur = AppOverviewService._range_scores(db, device_id, start, end)
        prev_start = start - timedelta(days=days)
        prev = AppOverviewService._range_scores(db, device_id, prev_start, start - timedelta(days=1))

        entries: List[Dict[str, Any]] = []
        for i in range(days):
            d = start + timedelta(days=i)
            sc = cur.get(d, [])
            ds = round(sum(sc) / len(sc), 1) if sc else None
            entries.append({"date": d, "day_score": ds, "band": band_for(ds) if ds is not None else None,
                            "status": "ok" if sc else "no_data", "completed_sessions": len(sc)})

        def avg(m: Dict[date, List[float]]) -> Optional[float]:
            ds = [sum(v) / len(v) for v in m.values() if v]
            return round(sum(ds) / len(ds), 1) if ds else None

        a, p = avg(cur), avg(prev)
        trend = None
        if a is not None and p is not None:
            trend = "flat" if abs(a - p) < 3 else ("up" if a > p else "down")
        return {"device_id": device_id, "today": today, "days": entries, "average_score": a,
                "previous_average_score": p, "trend": trend, "disclaimer": DISCLAIMER}

    @staticmethod
    def device_status(db: Session, device_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        today = StressService.local_today(db, now)
        dev = db.query(Device).filter(Device.id == device_id).first()
        st = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
        completed = db.query(StressSession).filter(
            StressSession.device_id == device_id, StressSession.local_date == today,
            StressSession.status == "completed").count()
        active = db.query(StressSession).filter(
            StressSession.device_id == device_id, StressSession.status == "active").first()

        connection = "unknown"
        last_seen = ensure_utc(dev.last_seen_at) if dev else None
        if dev:
            fresh = last_seen is not None and (now - last_seen).total_seconds() <= ONLINE_WINDOW_S
            connection = "online" if (dev.status == "online" and fresh) else "offline"
        return {
            "device_id": device_id, "registered": dev is not None,
            "name": dev.name if dev else None, "firmware_version": dev.firmware_version if dev else None,
            "connection": connection, "last_seen_at": last_seen,
            "present": bool(st and st.present), "privacy_on": bool(st and st.privacy_on),
            "privacy_since": st.privacy_since if st and st.privacy_on else None,
            "today": today, "completed_today": completed,
            "active_session": ({"session_id": active.id, "started_at": active.started_at,
                                "answered": len(active.responses), "total": len(StressService._plan(active))}
                               if active else None),
            "server_time": now,
        }

    @staticmethod
    def mood_summary(db: Session, device_id: str, period: str = "today",
                     now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        tz = user_tz(db)
        local_now = now.astimezone(tz)
        n_days = PERIOD_DAYS[period]
        start_local = datetime.combine(local_now.date() - timedelta(days=n_days - 1), datetime.min.time(), tzinfo=tz)
        since = start_local.astimezone(timezone.utc)
        rows = db.query(MoodEvent.emotion, MoodEvent.recorded_at).filter(
            MoodEvent.device_id == device_id, MoodEvent.is_valid.is_(True),
            MoodEvent.recorded_at >= since).order_by(MoodEvent.recorded_at).all()

        total = Counter()
        buckets: Dict[datetime, Counter] = defaultdict(Counter)
        for emotion, rec in rows:
            total[emotion] += 1
            lt = ensure_utc(rec).astimezone(tz)
            key = lt.replace(minute=0, second=0, microsecond=0) if period == "today" else \
                lt.replace(hour=0, minute=0, second=0, microsecond=0)
            buckets[key][emotion] += 1
        return {
            "device_id": device_id, "period": period, "since": since, "total": sum(total.values()),
            "counts": dict(total),
            "buckets": [{"start": k, "total": sum(v.values()), "counts": dict(v)} for k, v in sorted(buckets.items())],
        }

    @staticmethod
    def delete_mood_events(db: Session, device_id: str) -> int:
        n = db.query(MoodEvent).filter(MoodEvent.device_id == device_id).delete()
        db.commit()
        return n

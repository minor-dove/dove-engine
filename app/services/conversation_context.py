"""
Time- and person-aware context for a check-in: what time it is for the user, which stretch of time the
questions refer to, what was already talked about earlier today. Framing only; never a scoring input.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.preference import UserPreference
from app.models.stress import StressSession


def user_tz(db: Session):
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    try:
        return ZoneInfo(pref.timezone) if pref else timezone.utc
    except Exception:
        return timezone.utc


def daypart_for(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


def time_label(hour: int) -> str:
    if hour < 9:
        return "early morning"
    if hour < 12:
        return "mid-morning"
    if hour < 14:
        return "around lunchtime"
    if hour < 17:
        return "afternoon"
    if hour < 19:
        return "late afternoon, around the end of the work day"
    if hour < 21:
        return "evening"
    return "late evening"


def build_context(db: Session, device_id: str, now: Optional[datetime] = None,
                  exclude_session_id: Optional[str] = None) -> Dict[str, Any]:
    tz = user_tz(db)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    today = local.date()
    q = db.query(StressSession).filter(
        StressSession.device_id == device_id, StressSession.local_date == today,
        StressSession.status.in_(("completed", "incomplete")))
    if exclude_session_id:
        q = q.filter(StressSession.id != exclude_session_id)
    earlier: List[StressSession] = q.order_by(StressSession.started_at).all()

    daypart = daypart_for(local.hour)
    if earlier:
        window = "since we last talked"
    elif daypart == "morning":
        window = "so far this morning"
    else:
        window = "so far today"

    last_end = earlier[-1].ended_at if earlier else None
    mins_since = None
    if last_end is not None:
        if last_end.tzinfo is None:
            last_end = last_end.replace(tzinfo=timezone.utc)
        mins_since = int((local.astimezone(timezone.utc) - last_end).total_seconds() // 60)

    return {
        "local_time": local.strftime("%H:%M"),
        "weekday": local.strftime("%A"),
        "is_weekend": local.weekday() >= 5,
        "daypart": daypart,
        "time_label": time_label(local.hour),
        "window": window,
        "session_number_today": len(earlier) + 1,
        "minutes_since_last_session": mins_since,
        "earlier_today": [{"time": e.started_at.astimezone(tz).strftime("%H:%M") if e.started_at.tzinfo
                           else e.started_at.strftime("%H:%M"),
                           "summary": e.summary or ""} for e in earlier],
    }


def render_context(ctx: Dict[str, Any]) -> str:
    lines = [f"It is {ctx['weekday']} {ctx['local_time']} ({ctx['time_label']}; "
             f"{'weekend' if ctx['is_weekend'] else 'weekday'}) for the user.",
             f"This is check-in number {ctx['session_number_today']} today. "
             f"The questions are about the time window: \"{ctx['window']}\"."]
    if ctx["earlier_today"]:
        talked = "; ".join(f"{e['time']}: {e['summary'] or 'brief chat'}" for e in ctx["earlier_today"])
        lines.append(f"Earlier today you already talked about: {talked}. Do not repeat those questions; "
                     "build on them if relevant.")
    return "\n".join(lines)

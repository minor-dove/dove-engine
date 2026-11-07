"""
Stress assessment service: runs a structured session, scores it from the user's answers only,
and aggregates the daily score. Emotion data is passed to the LLM purely as framing context.
"""

import json
import logging
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.conversation import ConversationMessage, ConversationSession
from app.models.mood import MoodEvent
from app.models.preference import UserPreference
from app.models.stress import StressItemResponse, StressSession
from app.services import llm_service
from app.services.llm_service import LLMService
from app.services.memory_service import MemoryService
from app.services.stress_items import (
    ITEMS, REVERSE_ITEMS, band_for, compute_score, item_stress_value, plan_items,
)

logger = logging.getLogger(__name__)

DISCLAIMER = "This is a perceived-stress indicator, not a medical assessment."

PERSONA = (
    "You are Dove, a gentle desk pet running a short, friendly check-in. "
    "Speak in 1-2 short sentences. Never diagnose. Treat emotion hints as unproven; "
    "do not say 'I see you are sad'."
)

_WORD_VALUES = [
    (r"\b(not at all|never|none|zero|nope)\b", 0),
    (r"\b(very often|a lot|always|constantly|all day|extremely|totally)\b", 4),
    (r"\b(fairly often|often|quite|pretty much|a good bit)\b", 3),
    (r"\b(sometimes|somewhat|moderately|a few times|so so)\b", 2),
    (r"\b(a little|slightly|rarely|barely|once)\b", 1),
]


def heuristic_value(text: str) -> Optional[int]:
    """Offline fallback: map frequency words / a bare digit 0-4 to a value."""
    t = text.lower()
    m = re.fullmatch(r"\s*([0-4])\s*", t)
    if m:
        return int(m.group(1))
    for pattern, val in _WORD_VALUES:
        if re.search(pattern, t):
            return val
    return None


class StressService:

    # ---------- helpers ----------
    @staticmethod
    def local_today(db: Session) -> date:
        pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
        try:
            tz = ZoneInfo(pref.timezone) if pref else timezone.utc
        except Exception:
            tz = timezone.utc
        return datetime.now(timezone.utc).astimezone(tz).date()

    @staticmethod
    def emotion_summary(db: Session, device_id: str, hours: int = 3) -> str:
        """Framing context only. Never used for scoring."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = db.query(MoodEvent.emotion).filter(
            MoodEvent.device_id == device_id, MoodEvent.is_valid.is_(True),
            MoodEvent.recorded_at >= since).all()
        if not rows:
            return "no recent expression data"
        c = Counter(r[0] for r in rows)
        top = ", ".join(f"{k.lower()} x{v}" for k, v in c.most_common(3))
        return f"last {hours}h expression counts: {top}"

    @staticmethod
    def _plan(s: StressSession) -> List[int]:
        return json.loads(s.item_plan)

    @staticmethod
    def _memory_context(db: Session, query: str) -> str:
        mems = MemoryService.search_memories(db, query, limit=3)
        return "; ".join(m.content for m in mems) if mems else "none"

    @staticmethod
    def _compose(db: Session, s: StressSession, item_id: Optional[int], answer: Optional[str],
                 next_item_id: Optional[int], clarify: bool = False) -> Dict[str, Any]:
        """
        One LLM call: score `answer` against `item_id` AND phrase the next spoken line.
        Returns {value, confidence, evidence, reply}; falls back to heuristics offline.
        """
        next_q = ITEMS.get(next_item_id) if next_item_id else None
        mem = StressService._memory_context(db, (answer or "") + " " + (next_q or ""))
        emo = StressService.emotion_summary(db, s.device_id)

        out: Dict[str, Any] = {}
        if answer is not None and item_id is not None:
            sys_p = (PERSONA + " Return ONLY JSON: "
                     '{"value": 0-4 or null, "confidence": 0-1, "evidence": "short quote", "reply": "text"}. '
                     "value = how often/strongly the user says the statement was true today "
                     "(0 not at all, 1 a little, 2 sometimes, 3 fairly often, 4 very often); "
                     "null if the answer is unclear. reply = brief warm acknowledgement + the next question "
                     "(rephrase naturally, same meaning), or a clarifying question if value is null.")
            usr = (f"Question asked: {ITEMS[item_id]}\nUser answer: {answer}\n"
                   f"Next question to ask: {next_q or 'NONE (session is ending; just thank them warmly)'}\n"
                   f"Memories about the user: {mem}\nExpression hint (unproven): {emo}")
            llm = llm_service.generate_json(sys_p, usr)
            if llm is None:  # offline / failed: deterministic keyword fallback
                out = {"value": heuristic_value(answer)}
            else:
                out = dict(llm)
                v = out.get("value")
                valid = isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 4
                out["value"] = int(v) if valid else None
            if not out.get("evidence"):
                out["evidence"] = answer[:120]
        if not out.get("reply"):
            if answer is not None and out.get("value") is None:
                out["reply"] = ("Thanks for sharing. Could you tell me roughly how often — "
                                "not at all, a little, sometimes, fairly often, or very often?")
            else:
                ack = "Thanks for telling me. " if answer is not None else ""
                out["reply"] = ack + (next_q or "That's all for now, take care of yourself.")
        return out

    # ---------- lifecycle ----------
    @staticmethod
    def start_session(db: Session, device_id: str, mqtt_publisher: Optional[Any] = None) -> Dict[str, Any]:
        active = db.query(StressSession).filter(
            StressSession.device_id == device_id, StressSession.status == "active").first()
        if active:
            return StressService.describe(db, active, resumed=True)

        counts: Counter = Counter()
        for (iid,) in db.query(StressItemResponse.item_id).join(
                StressSession, StressSession.id == StressItemResponse.session_id).filter(
                StressSession.device_id == device_id).all():
            counts[iid] += 1
        plan = plan_items(counts)

        conv = ConversationSession(device_id=device_id, trigger_type="stress_session")
        db.add(conv)
        db.flush()
        s = StressSession(device_id=device_id, conversation_session_id=conv.id,
                          local_date=StressService.local_today(db), item_plan=json.dumps(plan))
        db.add(s)
        db.flush()

        opener = StressService._compose(db, s, None, None, plan[0])["reply"]
        question = "Hi, it's Dove. Mind a quick check-in? " + opener
        db.add(ConversationMessage(session_id=conv.id, role="assistant", content=question))
        db.commit()
        db.refresh(s)

        if mqtt_publisher:
            mqtt_publisher.publish_command(device_id, "session_start",
                                           {"session_id": s.id, "max_s": 600})
            mqtt_publisher.publish_command(device_id, "speak", {"session_id": s.id, "text": question})
        return StressService.describe(db, s, question=question)

    @staticmethod
    def submit_answer(db: Session, session_id: str, text: str,
                      mqtt_publisher: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        s = db.query(StressSession).filter(StressSession.id == session_id).first()
        if not s:
            return None
        if s.status != "active":
            return StressService.describe(db, s)

        plan = StressService._plan(s)
        item_id = plan[s.current_index]
        is_last = s.current_index + 1 >= len(plan)
        next_item = None if is_last else plan[s.current_index + 1]

        db.add(ConversationMessage(session_id=s.conversation_session_id, role="user", content=text.strip()))
        out = StressService._compose(db, s, item_id, text, next_item)
        value = out.get("value")

        if value is None and not s.clarify_used:
            s.clarify_used = True
            reply = ("Thanks for sharing. Roughly how often was that today: not at all, a little, "
                     "sometimes, fairly often, or very often?")
            face = "curious"
        else:
            db.add(StressItemResponse(session_id=s.id, item_id=item_id, value=value,
                                      confidence=out.get("confidence"), evidence=out.get("evidence")))
            s.current_index += 1
            s.clarify_used = False
            reply = out["reply"]
            face = "neutral"
            if value is not None:
                st = item_stress_value(item_id, value)
                face = "concerned" if st >= 3 else "happy" if st <= 1 else "neutral"
            if is_last:
                db.flush()
                return StressService._finish(db, s, closing_prefix=reply, face=face,
                                             mqtt_publisher=mqtt_publisher)

        db.add(ConversationMessage(session_id=s.conversation_session_id, role="assistant", content=reply))
        db.commit()
        if mqtt_publisher:
            mqtt_publisher.publish_command(s.device_id, "face", {"emotion": face})
            mqtt_publisher.publish_command(s.device_id, "speak", {"session_id": s.id, "text": reply})
        return StressService.describe(db, s, question=reply, face=face)

    @staticmethod
    def _finish(db: Session, s: StressSession, closing_prefix: str = "", face: str = "neutral",
                mqtt_publisher: Optional[Any] = None, status: Optional[str] = None) -> Dict[str, Any]:
        answers = [(r.item_id, r.value) for r in s.responses]
        score = compute_score(answers)
        s.score = score
        s.status = status or ("completed" if score is not None else "incomplete")
        s.ended_at = datetime.now(timezone.utc)
        conv = db.query(ConversationSession).filter(ConversationSession.id == s.conversation_session_id).first()
        if conv:
            conv.is_active = False
            conv.ended_at = s.ended_at
        if score is not None:
            closing = closing_prefix or "That's all for now, take care of yourself."
        else:
            closing = "Thanks for chatting with me. We'll try again later."
        if conv:
            db.add(ConversationMessage(session_id=conv.id, role="assistant", content=closing))
        db.commit()
        if mqtt_publisher:
            mqtt_publisher.publish_command(s.device_id, "speak", {"session_id": s.id, "text": closing})
            mqtt_publisher.publish_command(s.device_id, "session_end", {"session_id": s.id, "score": score})
        return StressService.describe(db, s, question=closing, face=face)

    @staticmethod
    def abort_session(db: Session, session_id: str, mqtt_publisher: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        s = db.query(StressSession).filter(StressSession.id == session_id).first()
        if not s:
            return None
        if s.status != "active":
            return StressService.describe(db, s)
        return StressService._finish(db, s, status="aborted", mqtt_publisher=mqtt_publisher)

    @staticmethod
    def describe(db: Session, s: StressSession, question: Optional[str] = None,
                 face: Optional[str] = None, resumed: bool = False) -> Dict[str, Any]:
        plan = StressService._plan(s)
        return {
            "session_id": s.id, "device_id": s.device_id, "status": s.status,
            "local_date": s.local_date, "progress": {"answered": len(s.responses), "total": len(plan)},
            "question": question, "face": face, "resumed": resumed,
            "score": s.score, "band": band_for(s.score) if s.score is not None else None,
            "items": [{"item_id": r.item_id, "value": r.value, "reverse_scored": r.item_id in REVERSE_ITEMS,
                       "confidence": r.confidence, "evidence": r.evidence} for r in s.responses],
            "disclaimer": DISCLAIMER,
        }

    # ---------- day aggregation ----------
    @staticmethod
    def day_report(db: Session, device_id: str, day: date) -> Dict[str, Any]:
        sessions = db.query(StressSession).filter(
            StressSession.device_id == device_id, StressSession.local_date == day,
            StressSession.status == "completed").order_by(StressSession.started_at).all()
        scores = [x.score for x in sessions if x.score is not None]
        day_score = round(sum(scores) / len(scores), 1) if scores else None
        return {
            "device_id": device_id, "date": day,
            "day_score": day_score, "band": band_for(day_score) if day_score is not None else None,
            "status": "ok" if scores else "no_data",
            "completed_sessions": len(scores),
            "sessions": [{"session_id": x.id, "score": x.score, "started_at": x.started_at} for x in sessions],
            "disclaimer": DISCLAIMER,
        }

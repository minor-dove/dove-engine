"""
Deterministic Trigger Engine.
Evaluates mood observations, tracks 10-consecutive Angry/Sad streaks,
enforces 30-minute proactive cooldowns, quiet hours, and starter rotation.
All trigger logic is deterministic and decoupled from the LLM.
"""

from datetime import datetime, timezone, time, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.core.config import settings
from app.core.security import inspect_payload_for_privacy_violation, is_timestamp_fresh, PrivacyViolationError, ensure_utc
from app.models.device import Device
from app.models.mood import MoodEvent, MoodStreak, EMOTION_MAP
from app.models.proactive import ProactiveCooldown, ProactiveTriggerLog
from app.models.starter import ConversationStarter
from app.models.conversation import ConversationSession, ConversationMessage
from app.models.preference import UserPreference
from app.schemas.mood import MoodEventCreate


def is_within_quiet_hours(now_dt: datetime, quiet_start_str: str, quiet_end_str: str, tz_name: str) -> bool:
    """
    Checks if the given UTC datetime falls within quiet hours in user's timezone.
    Handles overnight spans (e.g. 22:00 to 07:00).
    """
    try:
        user_tz = ZoneInfo(tz_name)
        local_dt = now_dt.astimezone(user_tz)
    except Exception:
        local_dt = now_dt  # fallback to UTC if timezone invalid

    local_time = local_dt.time()
    
    start_parts = [int(p) for p in quiet_start_str.split(":")]
    end_parts = [int(p) for p in quiet_end_str.split(":")]
    
    start_time = time(hour=start_parts[0], minute=start_parts[1])
    end_time = time(hour=end_parts[0], minute=end_parts[1])

    if start_time <= end_time:
        # e.g., 14:00 to 18:00
        return start_time <= local_time <= end_time
    else:
        # Overnight e.g., 22:00 to 07:00
        return local_time >= start_time or local_time <= end_time


class TriggerEngine:
    """
    Core deterministic engine for mood streak tracking and proactive conversation triggers.
    """

    @staticmethod
    def ingest_mood_event(db: Session, event_data: MoodEventCreate) -> Dict[str, Any]:
        """
        Ingests and validates a mood event from the edge device.
        Updates Angry/Sad streaks and evaluates proactive triggers.
        """
        # 1. Privacy inspection: ensure raw camera, image or face data is absent
        inspect_payload_for_privacy_violation(event_data.model_dump())

        # 2. Timestamp freshness validation
        if not is_timestamp_fresh(
            event_data.recorded_at,
            max_age_seconds=settings.MOOD_EVENT_MAX_AGE_SECONDS
        ):
            return {
                "status": "ignored",
                "reason": "stale_or_future_timestamp",
                "event_id": event_data.event_id
            }

        # 3. Deduplication: reject already processed event_id
        existing_event = db.query(MoodEvent).filter(MoodEvent.event_id == event_data.event_id).first()
        if existing_event:
            return {
                "status": "duplicate",
                "reason": "event_id_already_processed",
                "event_id": event_data.event_id
            }

        # Ensure device exists and update heartbeat
        device = db.query(Device).filter(Device.id == event_data.device_id).first()
        if not device:
            device = Device(
                id=event_data.device_id,
                name="DOVE Desk Pet",
                status="online",
                last_seen_at=datetime.now(timezone.utc)
            )
            db.add(device)
        else:
            device.status = "online"
            device.last_seen_at = datetime.now(timezone.utc)

        # 4. Out-of-order check
        last_event = (
            db.query(MoodEvent)
            .filter(MoodEvent.device_id == event_data.device_id, MoodEvent.is_valid.is_(True))
            .order_by(MoodEvent.recorded_at.desc())
            .first()
        )

        is_out_of_order = False
        if last_event and ensure_utc(last_event.recorded_at) > ensure_utc(event_data.recorded_at):
            is_out_of_order = True

        emotion_name = EMOTION_MAP[event_data.mood_id]
        
        # Persist valid mood event
        mood_event = MoodEvent(
            event_id=event_data.event_id,
            device_id=event_data.device_id,
            mood_id=event_data.mood_id,
            emotion=emotion_name,
            recorded_at=event_data.recorded_at,
            received_at=datetime.now(timezone.utc),
            is_valid=not is_out_of_order
        )
        db.add(mood_event)

        # If out-of-order, do not update streak
        if is_out_of_order:
            db.commit()
            return {
                "status": "ignored",
                "reason": "out_of_order_event",
                "event_id": event_data.event_id
            }

        # 5. Streak calculation and update
        streak_result = TriggerEngine._update_mood_streaks(
            db=db,
            device_id=event_data.device_id,
            mood_id=event_data.mood_id,
            emotion_name=emotion_name,
            event_time=event_data.recorded_at,
            last_event_time=last_event.recorded_at if last_event else None
        )

        # 6. Check if qualifying proactive trigger criteria is met
        trigger_outcome = TriggerEngine._evaluate_proactive_trigger(
            db=db,
            device_id=event_data.device_id,
            mood_id=event_data.mood_id,
            streak_result=streak_result
        )

        db.commit()

        return {
            "status": "processed",
            "event_id": event_data.event_id,
            "device_id": event_data.device_id,
            "emotion": emotion_name,
            "streak": streak_result,
            "trigger_outcome": trigger_outcome
        }

    @staticmethod
    def _update_mood_streaks(
        db: Session,
        device_id: str,
        mood_id: int,
        emotion_name: str,
        event_time: datetime,
        last_event_time: Optional[datetime]
    ) -> Dict[str, Any]:
        """
        Updates streak counts for Angry (0) and Sad (4).
        Resets streak on missing observations (> 150s gap) or when a different mood occurs.
        """
        # Fetch existing streaks for Angry (0) and Sad (4)
        angry_streak = db.query(MoodStreak).filter(
            MoodStreak.device_id == device_id,
            MoodStreak.mood_id == 0
        ).first()

        if not angry_streak:
            angry_streak = MoodStreak(
                device_id=device_id,
                mood_id=0,
                emotion="Angry",
                current_count=0,
                qualifying_streak_triggered=False
            )
            db.add(angry_streak)

        sad_streak = db.query(MoodStreak).filter(
            MoodStreak.device_id == device_id,
            MoodStreak.mood_id == 4
        ).first()

        if not sad_streak:
            sad_streak = MoodStreak(
                device_id=device_id,
                mood_id=4,
                emotion="Sad",
                current_count=0,
                qualifying_streak_triggered=False
            )
            db.add(sad_streak)

        # Check gap between consecutive observations
        is_gap_broken = False
        if last_event_time:
            gap_seconds = (ensure_utc(event_time) - ensure_utc(last_event_time)).total_seconds()
            if gap_seconds > settings.MOOD_MAX_EVENT_GAP_SECONDS:
                is_gap_broken = True

        # Process mood ID
        if mood_id == 0:  # Angry
            # Reset Sad streak completely
            sad_streak.current_count = 0
            sad_streak.qualifying_streak_triggered = False

            if is_gap_broken:
                angry_streak.current_count = 1
                angry_streak.qualifying_streak_triggered = False
            else:
                angry_streak.current_count += 1

            angry_streak.last_event_time = event_time
            angry_streak.updated_at = datetime.now(timezone.utc)

            return {
                "eligible_mood": "Angry",
                "count": angry_streak.current_count,
                "qualifying_streak_triggered": angry_streak.qualifying_streak_triggered,
                "gap_broken": is_gap_broken
            }

        elif mood_id == 4:  # Sad
            # Reset Angry streak completely
            angry_streak.current_count = 0
            angry_streak.qualifying_streak_triggered = False

            if is_gap_broken:
                sad_streak.current_count = 1
                sad_streak.qualifying_streak_triggered = False
            else:
                sad_streak.current_count += 1

            sad_streak.last_event_time = event_time
            sad_streak.updated_at = datetime.now(timezone.utc)

            return {
                "eligible_mood": "Sad",
                "count": sad_streak.current_count,
                "qualifying_streak_triggered": sad_streak.qualifying_streak_triggered,
                "gap_broken": is_gap_broken
            }

        else:
            # Any non-qualifying mood (Disgust, Fear, Happy, Surprise, Neutral)
            # completely resets both Angry and Sad streaks
            angry_streak.current_count = 0
            angry_streak.qualifying_streak_triggered = False
            sad_streak.current_count = 0
            sad_streak.qualifying_streak_triggered = False

            return {
                "eligible_mood": None,
                "count": 0,
                "qualifying_streak_triggered": False,
                "gap_broken": is_gap_broken
            }

    @staticmethod
    def _evaluate_proactive_trigger(
        db: Session,
        device_id: str,
        mood_id: int,
        streak_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Determines if a proactive conversation should be triggered based on sustained Angry or Sad streaks.
        Enforces cooldowns, quiet hours, active conversation checks, and atomic cooldown reservation.
        """
        # Only Angry (0) and Sad (4) can trigger
        if mood_id not in (0, 4):
            return {"action": "none", "reason": "non_triggering_mood"}

        eligible_mood = streak_result["eligible_mood"]
        current_count = streak_result["count"]
        already_triggered = streak_result["qualifying_streak_triggered"]

        trigger_type = f"mood_{eligible_mood.lower()}"

        # Must meet exact required threshold (10 consecutive)
        if current_count < settings.MOOD_CONSECUTIVE_REQUIRED:
            return {
                "action": "accumulating",
                "current_count": current_count,
                "required": settings.MOOD_CONSECUTIVE_REQUIRED
            }

        # Prevent repeated triggers while same qualifying mood persists
        if already_triggered:
            return {
                "action": "skipped",
                "reason": "already_triggered_for_current_streak"
            }

        # Check if a conversation is already active on this device
        active_session = db.query(ConversationSession).filter(
            ConversationSession.device_id == device_id,
            ConversationSession.is_active.is_(True)
        ).first()

        if active_session:
            # Attach newer mood observation as context to the active session rather than opening duplicate
            # Record log as skipped due to active conversation
            db.add(ProactiveTriggerLog(
                device_id=device_id,
                trigger_type=trigger_type,
                status="skipped",
                reason="conversation_already_active"
            ))
            return {
                "action": "skipped",
                "reason": "conversation_already_active",
                "session_id": active_session.id
            }

        # Check user preferences (proactive enabled & quiet hours)
        pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
        if not pref:
            pref = UserPreference(id=1)
            db.add(pref)
            db.flush()

        if not pref.proactive_enabled:
            db.add(ProactiveTriggerLog(
                device_id=device_id,
                trigger_type=trigger_type,
                status="skipped",
                reason="proactive_disabled_by_user"
            ))
            return {"action": "skipped", "reason": "proactive_disabled_by_user"}

        now_utc = datetime.now(timezone.utc)
        if is_within_quiet_hours(now_utc, pref.quiet_hours_start, pref.quiet_hours_end, pref.timezone):
            db.add(ProactiveTriggerLog(
                device_id=device_id,
                trigger_type=trigger_type,
                status="skipped",
                reason="quiet_hours_active"
            ))
            return {"action": "skipped", "reason": "quiet_hours_active"}

        # Check proactive cooldown
        cooldown = db.query(ProactiveCooldown).filter(ProactiveCooldown.device_id == device_id).with_for_update().first()
        if not cooldown:
            cooldown = ProactiveCooldown(
                device_id=device_id,
                last_proactive_at=None,
                cooldown_until=None
            )
            db.add(cooldown)
            db.flush()

        if cooldown.cooldown_until and ensure_utc(cooldown.cooldown_until) > now_utc:
            db.add(ProactiveTriggerLog(
                device_id=device_id,
                trigger_type=trigger_type,
                status="skipped",
                reason="cooldown_active"
            ))
            return {
                "action": "skipped",
                "reason": "cooldown_active",
                "cooldown_until": cooldown.cooldown_until.isoformat()
            }

        # ATOMIC COOLDOWN RESERVATION
        cooldown_duration = timedelta(minutes=pref.cooldown_minutes)
        cooldown.last_proactive_at = now_utc
        cooldown.cooldown_until = now_utc + cooldown_duration
        cooldown.last_trigger_type = trigger_type
        cooldown.updated_at = now_utc

        # Mark streak as triggered so next events don't trigger repeatedly
        streak = db.query(MoodStreak).filter(
            MoodStreak.device_id == device_id,
            MoodStreak.mood_id == mood_id
        ).first()
        if streak:
            streak.qualifying_streak_triggered = True

        # Pick starter from library using rotation (least used)
        starter_cat = eligible_mood.lower()
        starter = (
            db.query(ConversationStarter)
            .filter(ConversationStarter.category == starter_cat, ConversationStarter.is_active.is_(True))
            .order_by(ConversationStarter.usage_count.asc(), ConversationStarter.last_used_at.asc().nulls_first())
            .first()
        )

        starter_text = starter.text if starter else "Hey, just checking in. How are you doing today?"
        if starter:
            starter.usage_count += 1
            starter.last_used_at = now_utc

        # Create new conversation session
        session = ConversationSession(
            device_id=device_id,
            is_active=True,
            trigger_type=trigger_type,
            started_at=now_utc
        )
        db.add(session)
        db.flush()

        # Add initial assistant check-in message
        assistant_msg = ConversationMessage(
            session_id=session.id,
            role="assistant",
            content=starter_text,
            mood_context=eligible_mood,
            delivery_status="delivered",
            created_at=now_utc
        )
        db.add(assistant_msg)

        # Log accepted trigger
        db.add(ProactiveTriggerLog(
            device_id=device_id,
            trigger_type=trigger_type,
            status="delivered",
            reason="sustained_mood_qualified",
            starter_id=starter.id if starter else None,
            created_at=now_utc
        ))

        return {
            "action": "initiated",
            "trigger_type": trigger_type,
            "session_id": session.id,
            "starter_text": starter_text,
            "cooldown_until": cooldown.cooldown_until.isoformat()
        }

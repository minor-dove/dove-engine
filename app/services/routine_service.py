"""
Routine Service: Manages scheduled morning, midday, evening, and night check-ins.
Prevents duplicate daily routines and honors user preferences.
"""

from typing import List, Optional, Any, Dict
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.routine import RoutineExecution
from app.models.preference import UserPreference
from app.models.proactive import ProactiveCooldown, ProactiveTriggerLog
from app.models.starter import ConversationStarter
from app.models.conversation import ConversationSession, ConversationMessage
from app.services.trigger_engine import is_within_quiet_hours


class RoutineService:
    @staticmethod
    def check_and_execute_routines(
        db: Session,
        device_id: str = "dove-esp32-01",
        mqtt_publisher: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Periodically invoked by background scheduler.
        Checks if morning, midday, evening, or night routine is due right now.
        """
        pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
        if not pref or not pref.proactive_enabled:
            return []

        now_utc = datetime.now(timezone.utc)
        try:
            user_tz = ZoneInfo(pref.timezone)
            local_dt = now_utc.astimezone(user_tz)
        except Exception:
            local_dt = now_utc

        today_local = local_dt.date()
        current_time_str = local_dt.strftime("%H:%M")

        # Map routine types to configured times
        routines = [
            ("morning", pref.morning_time, True),
            ("midday", pref.midday_time, True),
            ("evening", pref.evening_time, True),
            ("night", pref.night_time, pref.night_enabled),
        ]

        executed = []
        for routine_type, configured_time, is_enabled in routines:
            if not is_enabled:
                continue

            # Parse routine time
            r_hour, r_min = [int(p) for p in configured_time.split(":")]
            routine_dt_local = local_dt.replace(hour=r_hour, minute=r_min, second=0, microsecond=0)
            
            # Check if we are within a 15-minute trigger window after scheduled time
            diff_seconds = (local_dt - routine_dt_local).total_seconds()
            if not (0 <= diff_seconds <= 900):  # 0 to 15 minutes window
                continue

            # Check if this routine was already executed today
            already_done = db.query(RoutineExecution).filter(
                RoutineExecution.routine_type == routine_type,
                func.date(RoutineExecution.scheduled_for) == today_local
            ).first()

            if already_done:
                continue

            # Check quiet hours
            if is_within_quiet_hours(now_utc, pref.quiet_hours_start, pref.quiet_hours_end, pref.timezone):
                continue

            # Check proactive cooldown
            cooldown = db.query(ProactiveCooldown).filter(ProactiveCooldown.device_id == device_id).with_for_update().first()
            if not cooldown:
                cooldown = ProactiveCooldown(device_id=device_id)
                db.add(cooldown)
                db.flush()

            if cooldown.cooldown_until and cooldown.cooldown_until > now_utc:
                # Cooldown active, skip routine check-in
                continue

            # Atomically reserve cooldown
            trigger_type = f"routine_{routine_type}"
            cooldown.last_proactive_at = now_utc
            cooldown.cooldown_until = now_utc + timedelta(minutes=pref.cooldown_minutes)
            cooldown.last_trigger_type = trigger_type
            cooldown.updated_at = now_utc

            # Pick starter from library
            starter = (
                db.query(ConversationStarter)
                .filter(ConversationStarter.category == routine_type, ConversationStarter.is_active.is_(True))
                .order_by(ConversationStarter.usage_count.asc())
                .first()
            )
            starter_text = starter.text if starter else f"Good {routine_type}! How are things going?"
            if starter:
                starter.usage_count += 1
                starter.last_used_at = now_utc

            # Create conversation session
            session = ConversationSession(
                device_id=device_id,
                is_active=True,
                trigger_type=trigger_type,
                started_at=now_utc
            )
            db.add(session)
            db.flush()

            # Create initial message
            msg = ConversationMessage(
                session_id=session.id,
                role="assistant",
                content=starter_text,
                mood_context=routine_type.capitalize(),
                delivery_status="delivered",
                created_at=now_utc
            )
            db.add(msg)

            # Record routine execution
            exec_record = RoutineExecution(
                routine_type=routine_type,
                scheduled_for=now_utc,
                executed_at=now_utc,
                status="completed"
            )
            db.add(exec_record)

            db.add(ProactiveTriggerLog(
                device_id=device_id,
                trigger_type=trigger_type,
                status="delivered",
                reason="daily_schedule_matched",
                starter_id=starter.id if starter else None,
                created_at=now_utc
            ))

            db.commit()

            # Publish speech prompt to device via MQTT
            if mqtt_publisher:
                try:
                    mqtt_publisher.publish_command(
                        device_id=device_id,
                        command_type="speak",
                        payload={"text": starter_text, "session_id": session.id, "routine": routine_type}
                    )
                except Exception:
                    pass

            executed.append({
                "routine_type": routine_type,
                "session_id": session.id,
                "starter_text": starter_text
            })

        return executed

    @staticmethod
    def list_executions(db: Session, limit: int = 50) -> List[RoutineExecution]:
        return db.query(RoutineExecution).order_by(RoutineExecution.executed_at.desc()).limit(limit).all()

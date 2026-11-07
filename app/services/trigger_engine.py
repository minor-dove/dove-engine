"""
Mood ingestion.
Validates, dedupes and stores per-minute emotion observations from the device.
Emotion events are SIGNAL ONLY (they frame questions); they never start sessions or affect scores.
Session scheduling lives in stress_planner.py. (The old 10-in-a-row Angry/Sad trigger was removed.)
"""

from datetime import datetime, timezone, time, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.core.config import settings
from app.core.security import inspect_payload_for_privacy_violation, is_timestamp_fresh, PrivacyViolationError, ensure_utc
from app.models.device import Device
from app.models.device_state import DeviceState
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
        Stores the observation and marks the user as present.
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

        # 2b. Privacy mode: drop anything that arrives while the device says it is private
        state = db.query(DeviceState).filter(DeviceState.device_id == event_data.device_id).first()
        if state and state.privacy_on:
            return {"status": "ignored", "reason": "privacy_mode", "event_id": event_data.event_id}

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
        if not is_out_of_order:
            from app.services.device_state_service import DeviceStateService
            DeviceStateService.set_presence(db, event_data.device_id, True, commit=False)

        # If out-of-order, stored but flagged invalid
        if is_out_of_order:
            db.commit()
            return {
                "status": "ignored",
                "reason": "out_of_order_event",
                "event_id": event_data.event_id
            }

        db.commit()

        return {
            "status": "processed",
            "event_id": event_data.event_id,
            "device_id": event_data.device_id,
            "emotion": emotion_name
        }

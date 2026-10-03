"""
Mood Ingestion API Router.
Provides REST endpoints for edge device mood observation ingestion,
streak inspection, and proactive check-in trigger testing.
Mirrors the MQTT topic dove/devices/{device_id}/events.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.models.mood import MoodEvent, MoodStreak
from app.schemas.mood import MoodEventCreate, MoodEventResponse, MoodStreakResponse
from app.services.trigger_engine import TriggerEngine
from app.mqtt.client import mqtt_service

router = APIRouter(prefix="/mood", tags=["Mood & Edge Sensory"])


@router.post("/events", status_code=status.HTTP_200_OK)
def ingest_mood_event(
    event_in: MoodEventCreate,
    db: Session = Depends(get_database)
) -> Dict[str, Any]:
    """
    Ingests an edge mood observation (0:Angry, 1:Disgust, 2:Fear, 3:Happy, 4:Sad, 5:Surprise, 6:Neutral).
    Strictly forbids camera/image keys.
    Updates consecutive emotion streaks and initiates proactive check-ins on 10 consecutive Sad/Angry events.
    """
    result = TriggerEngine.ingest_mood_event(db=db, event_data=event_in)

    # If trigger initiated a proactive check-in, dispatch speech command to ESP32
    if result.get("trigger_outcome", {}).get("action") == "initiated":
        outcome = result["trigger_outcome"]
        try:
            mqtt_service.publish_command(
                device_id=event_in.device_id,
                command_type="speak",
                payload={
                    "text": outcome.get("starter_text"),
                    "session_id": outcome.get("session_id"),
                    "trigger_type": outcome.get("trigger_type")
                }
            )
        except Exception:
            pass

    return result


@router.get("/streaks/{device_id}", response_model=List[MoodStreakResponse])
def get_device_mood_streaks(
    device_id: str,
    db: Session = Depends(get_database)
):
    """Retrieves current consecutive emotion streaks for a given device."""
    return db.query(MoodStreak).filter(MoodStreak.device_id == device_id).all()


@router.get("/events/{device_id}", response_model=List[MoodEventResponse])
def get_recent_mood_events(
    device_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_database)
):
    """Retrieves recent mood events recorded for a device."""
    return (
        db.query(MoodEvent)
        .filter(MoodEvent.device_id == device_id)
        .order_by(MoodEvent.recorded_at.desc())
        .limit(limit)
        .all()
    )

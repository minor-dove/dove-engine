"""
Mood Ingestion API Router.
Provides REST endpoints for edge device mood observation ingestion,
and recent-event inspection.
Mirrors the MQTT topic dove/devices/{device_id}/events.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.models.mood import MoodEvent
from app.schemas.mood import MoodEventCreate, MoodEventResponse
from app.schemas.app_api import MoodSummaryResponse
from app.services.app_overview_service import AppOverviewService
from app.services.trigger_engine import TriggerEngine

router = APIRouter(prefix="/mood", tags=["Mood & Edge Sensory"])


@router.post("/events", status_code=status.HTTP_200_OK)
def ingest_mood_event(
    event_in: MoodEventCreate,
    db: Session = Depends(get_database)
) -> Dict[str, Any]:
    """
    Ingests an edge mood observation (0:Angry, 1:Disgust, 2:Fear, 3:Happy, 4:Sad, 5:Surprise, 6:Neutral).
    Strictly forbids camera/image keys.
    Signal only: stored for question framing; never triggers sessions or affects scores.
    """
    return TriggerEngine.ingest_mood_event(db=db, event_data=event_in)


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


@router.get("/summary/{device_id}", response_model=MoodSummaryResponse)
def mood_summary(
    device_id: str,
    period: str = Query(default="today", pattern="^(today|week|month)$"),
    db: Session = Depends(get_database)
):
    """Expression-signal counts over a period (hourly buckets for today, daily otherwise). Never feeds the score."""
    return AppOverviewService.mood_summary(db, device_id, period=period)


@router.delete("/events/{device_id}")
def delete_mood_events(device_id: str, db: Session = Depends(get_database)) -> Dict[str, Any]:
    """Erase all stored expression signals for a device."""
    return {"device_id": device_id, "deleted": AppOverviewService.delete_mood_events(db, device_id)}

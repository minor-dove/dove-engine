"""Stress assessment API: start/answer sessions, fetch session and day reports."""

from datetime import date
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.mqtt.client import mqtt_service
from app.models.device import Device
from app.models.stress import StressSession
from app.schemas.app_api import DayHistoryResponse, SessionListResponse, SessionTranscriptResponse
from app.services.app_overview_service import AppOverviewService
from app.services.profile_service import ProfileService
from app.services.stress_service import StressService

router = APIRouter(prefix="/stress", tags=["Stress"])
DEFAULT_DEVICE = "dove-esp32-01"


class StartRequest(BaseModel):
    device_id: str = Field(default=DEFAULT_DEVICE, max_length=64)


class AnswerRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _publisher():
    return mqtt_service if mqtt_service.is_connected else None


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(device_id: str = DEFAULT_DEVICE, limit: int = Query(default=50, ge=1, le=200),
                  offset: int = Query(default=0, ge=0), day: Optional[date] = None,
                  status: Optional[str] = Query(default=None, pattern="^(active|completed|incomplete|aborted)$"),
                  db: Session = Depends(get_database)):
    """Check-in history (newest first) with per-session score. Perceived stress, not a diagnosis."""
    return AppOverviewService.list_sessions(db, device_id, limit=limit, offset=offset, day=day, status=status)


@router.get("/days", response_model=DayHistoryResponse)
def day_history(device_id: str = DEFAULT_DEVICE, days: int = Query(default=7, ge=1, le=90),
                end: Optional[date] = None, db: Session = Depends(get_database)):
    """Daily perceived-stress scores for the last `days` days (oldest first) plus trend vs the previous range."""
    return AppOverviewService.day_history(db, device_id, days=days, end=end)


@router.post("/sessions", status_code=201)
def start_session(body: StartRequest, db: Session = Depends(get_database)) -> Dict[str, Any]:
    if not db.query(Device).filter(Device.id == body.device_id).first():
        raise HTTPException(status_code=404, detail="Device not registered (POST /api/v1/devices first)")
    return StressService.start_session(db, body.device_id, mqtt_publisher=_publisher())


@router.post("/sessions/{session_id}/answer")
def answer(session_id: str, body: AnswerRequest, db: Session = Depends(get_database)) -> Dict[str, Any]:
    res = StressService.submit_answer(db, session_id, body.text, mqtt_publisher=_publisher())
    if res is None:
        raise HTTPException(status_code=404, detail="Stress session not found")
    return res


@router.post("/sessions/{session_id}/abort")
def abort(session_id: str, db: Session = Depends(get_database)) -> Dict[str, Any]:
    res = StressService.abort_session(db, session_id, mqtt_publisher=_publisher())
    if res is None:
        raise HTTPException(status_code=404, detail="Stress session not found")
    return res


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_database)) -> Dict[str, Any]:
    s = db.query(StressSession).filter(StressSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Stress session not found")
    return StressService.describe(db, s)


@router.get("/sessions/{session_id}/transcript", response_model=SessionTranscriptResponse)
def session_transcript(session_id: str, db: Session = Depends(get_database)):
    """What Dove and the user said in one check-in, with its score."""
    res = AppOverviewService.transcript(db, session_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Stress session not found")
    return res


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Session = Depends(get_database)):
    """Erase one check-in (its answers, transcript and derived memories). It no longer counts toward the day."""
    if not AppOverviewService.delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="Stress session not found")
    return Response(status_code=204)


@router.get("/days/{day}")
def day_report(day: date, device_id: str = DEFAULT_DEVICE, db: Session = Depends(get_database)) -> Dict[str, Any]:
    return StressService.day_report(db, device_id, day)


@router.get("/profile")
def get_profile(device_id: str = DEFAULT_DEVICE, db: Session = Depends(get_database)) -> Dict[str, Any]:
    """What Dove has learned from your check-ins (built only from what you said). Transparent by design."""
    return {"device_id": device_id, "sessions_learned_from": ProfileService.sessions_count(db, device_id),
            "profile": ProfileService.get(db, device_id)}


@router.delete("/profile")
def delete_profile(device_id: str = DEFAULT_DEVICE, db: Session = Depends(get_database)) -> Dict[str, Any]:
    """Forget everything learned about the person; the next check-in starts generic again."""
    return {"device_id": device_id, "deleted": ProfileService.reset(db, device_id)}

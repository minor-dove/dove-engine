"""Stress assessment API: start/answer sessions, fetch session and day reports."""

from datetime import date
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.mqtt.client import mqtt_service
from app.models.stress import StressSession
from app.services.stress_service import StressService

router = APIRouter(prefix="/stress", tags=["Stress"])
DEFAULT_DEVICE = "dove-esp32-01"


class StartRequest(BaseModel):
    device_id: str = Field(default=DEFAULT_DEVICE, max_length=64)


class AnswerRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _publisher():
    return mqtt_service if mqtt_service.is_connected else None


@router.post("/sessions", status_code=201)
def start_session(body: StartRequest, db: Session = Depends(get_database)) -> Dict[str, Any]:
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


@router.get("/days/{day}")
def day_report(day: date, device_id: str = DEFAULT_DEVICE, db: Session = Depends(get_database)) -> Dict[str, Any]:
    return StressService.day_report(db, device_id, day)

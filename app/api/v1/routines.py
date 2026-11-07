"""
Routines API Router.
Endpoints for routine execution history and manual routine triggers.
"""

from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.schemas.routine import RoutineExecutionResponse, RoutineTriggerRequest
from app.services.routine_service import RoutineService
from app.models.starter import ConversationStarter
from app.models.conversation import ConversationSession, ConversationMessage
from app.models.routine import RoutineExecution
from app.mqtt.client import mqtt_service

router = APIRouter(prefix="/routines", tags=["Routines"])


@router.get("/history", response_model=List[RoutineExecutionResponse])
def get_routine_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_database)
):
    """List historical executions of morning, midday, evening, and night routines."""
    return RoutineService.list_executions(db=db, limit=limit)


@router.post("/trigger")
def manually_trigger_routine(
    req: RoutineTriggerRequest,
    db: Session = Depends(get_database)
):
    """
    Manually triggers a proactive routine check-in (morning, midday, evening, night).
    Used by companion app to test routines.
    """
    valid_types = ["morning", "midday", "evening", "night"]
    if req.routine_type.lower() not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid routine type. Must be one of {valid_types}"
        )

    now_utc = datetime.now(timezone.utc)
    starter = (
        db.query(ConversationStarter)
        .filter(ConversationStarter.category == req.routine_type.lower(), ConversationStarter.is_active.is_(True))
        .first()
    )
    starter_text = starter.text if starter else f"Good {req.routine_type}! How are things going?"

    session = ConversationSession(
        device_id=req.device_id,
        is_active=True,
        trigger_type=f"routine_{req.routine_type.lower()}",
        started_at=now_utc
    )
    db.add(session)
    db.flush()

    msg = ConversationMessage(
        session_id=session.id,
        role="assistant",
        content=starter_text,
        mood_context=req.routine_type.capitalize(),
        delivery_status="delivered",
        created_at=now_utc
    )
    db.add(msg)

    exec_record = RoutineExecution(
        routine_type=req.routine_type.lower(),
        scheduled_for=now_utc,
        executed_at=now_utc,
        status="completed"
    )
    db.add(exec_record)
    db.commit()

    # Publish speech prompt to device via MQTT
    mqtt_service.publish_command(
        device_id=req.device_id,
        command_type="speak",
        payload={"text": starter_text, "session_id": session.id, "routine": req.routine_type}
    )

    return {
        "status": "triggered",
        "routine_type": req.routine_type,
        "session_id": session.id,
        "message": starter_text
    }

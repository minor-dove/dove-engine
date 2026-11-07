"""
Conversations API Router.
Endpoints for multi-turn sessions, message sending, and false-trigger marking.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_database
from app.models.conversation import ConversationSession
from app.schemas.conversation import (
    SessionResponse,
    SendMessageRequest,
    SendMessageResponse,
    MarkFalseTriggerRequest
)
from app.services.conversation_service import ConversationService
from app.services.memory_service import MemoryService
from app.mqtt.client import mqtt_service

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(
    device_id: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_database)
):
    """Lists conversation sessions."""
    query = db.query(ConversationSession).options(joinedload(ConversationSession.messages))
    if device_id:
        query = query.filter(ConversationSession.device_id == device_id)
    if is_active is not None:
        query = query.filter(ConversationSession.is_active == is_active)
    return query.order_by(ConversationSession.started_at.desc()).limit(limit).all()


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_database)):
    """Retrieves session details and its full message history."""
    session = (
        db.query(ConversationSession)
        .options(joinedload(ConversationSession.messages))
        .filter(ConversationSession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation session not found")
    return session


@router.post("/message", response_model=SendMessageResponse)
def send_message(req: SendMessageRequest, db: Session = Depends(get_database)):
    """
    Sends a user utterance to DOVE.
    Coordinates context retrieval, Groq generation, and persistence.
    """
    return ConversationService.handle_user_message(
        db=db,
        device_id=req.device_id,
        message_text=req.message,
        session_id=req.session_id,
        mqtt_publisher=mqtt_service
    )


@router.post("/sessions/{session_id}/false-trigger")
def mark_false_trigger(
    session_id: str,
    req: MarkFalseTriggerRequest,
    db: Session = Depends(get_database)
):
    """
    Marks a session as a false trigger.
    Excludes the session from future retrieval and purges all derived memories.
    """
    success = MemoryService.mark_false_trigger(db, session_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return {"status": "success", "session_id": session_id, "is_false_trigger": True}

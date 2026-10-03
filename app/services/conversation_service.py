"""
Conversation Service.
Coordinates multi-turn dialogue flow, 3-layer context assembly (history, structured data, RAG),
prompt synthesis, Groq invocation, turn persistence, and MQTT publishing.
"""

from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.core.config import settings
from app.models.conversation import ConversationSession, ConversationMessage
from app.models.task import TaskItem
from app.models.reminder import Reminder
from app.models.preference import UserPreference
from app.models.mood import MoodEvent
from app.services.llm_service import LLMService, DEFAULT_SYSTEM_PROMPT
from app.services.memory_service import MemoryService
from app.schemas.conversation import SendMessageResponse


class ConversationService:
    """
    Manages multi-turn conversations between the user and DOVE.
    """

    @staticmethod
    def get_or_create_active_session(
        db: Session,
        device_id: str,
        session_id: Optional[str] = None,
        trigger_type: str = "user_initiated"
    ) -> ConversationSession:
        """
        Retrieves the specified active session or creates a new one.
        """
        if session_id:
            session = db.query(ConversationSession).filter(
                ConversationSession.id == session_id,
                ConversationSession.is_active.is_(True)
            ).first()
            if session:
                return session

        # Look for any currently active session for this device
        active_session = db.query(ConversationSession).filter(
            ConversationSession.device_id == device_id,
            ConversationSession.is_active.is_(True)
        ).order_by(ConversationSession.started_at.desc()).first()

        if active_session:
            return active_session

        # Create a new session
        new_session = ConversationSession(
            device_id=device_id,
            is_active=True,
            trigger_type=trigger_type,
            started_at=datetime.now(timezone.utc)
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        return new_session

    @staticmethod
    def build_system_prompt(
        db: Session,
        device_id: str,
        user_query: str
    ) -> str:
        """
        Synthesizes the 3-layer context:
        1. Base persona
        2. Structured PostgreSQL data (tasks, reminders, preferences)
        3. Long-term semantic memories (RAG)
        4. Contextual mood observation (treated strictly as a hint, not a diagnosis)
        """
        prompt_parts = [DEFAULT_SYSTEM_PROMPT]

        # Layer 1: Structured application data
        # Fetch pending tasks (up to 5)
        pending_tasks = db.query(TaskItem).filter(
            TaskItem.status == "pending"
        ).order_by(TaskItem.due_date.asc().nulls_last()).limit(5).all()

        if pending_tasks:
            task_lines = [f"- {t.title}" + (f" (Due: {t.due_date.strftime('%Y-%m-%d %H:%M')})" if t.due_date else "") for t in pending_tasks]
            prompt_parts.append("\n[Structured State - Pending Tasks]:\n" + "\n".join(task_lines))

        # Fetch upcoming reminders
        now_utc = datetime.now(timezone.utc)
        upcoming_reminders = db.query(Reminder).filter(
            Reminder.status == "pending",
            Reminder.scheduled_time >= now_utc
        ).order_by(Reminder.scheduled_time.asc()).limit(3).all()

        if upcoming_reminders:
            reminder_lines = [f"- {r.message} at {r.scheduled_time.strftime('%H:%M UTC')}" for r in upcoming_reminders]
            prompt_parts.append("\n[Structured State - Upcoming Reminders]:\n" + "\n".join(reminder_lines))

        # Layer 2: Long-term semantic memories (RAG)
        relevant_memories = MemoryService.search_memories(db, user_query, limit=3)
        if relevant_memories:
            mem_lines = [f"- {m.content}" for m in relevant_memories]
            prompt_parts.append("\n[Long-term Memory (Facts User Genuinely Shared)]:\n" + "\n".join(mem_lines))

        # Layer 3: Recent mood observation
        latest_mood = (
            db.query(MoodEvent)
            .filter(MoodEvent.device_id == device_id, MoodEvent.is_valid.is_(True))
            .order_by(MoodEvent.recorded_at.desc())
            .first()
        )
        if latest_mood:
            prompt_parts.append(
                f"\n[Sensory Context]: Recent subtle expression observed: {latest_mood.emotion}. "
                "Remember: This is only a subtle environmental signal, not a proven fact. "
                "Do NOT say 'I see you are sad/angry'. Let the user lead."
            )

        return "\n".join(prompt_parts)

    @staticmethod
    def handle_user_message(
        db: Session,
        device_id: str,
        message_text: str,
        session_id: Optional[str] = None,
        mqtt_publisher: Optional[Any] = None
    ) -> SendMessageResponse:
        """
        Processes an incoming user message, builds multi-turn context,
        generates assistant reply, persists turns, and notifies hardware.
        """
        now_utc = datetime.now(timezone.utc)

        # 1. Get or create active session (User-initiated messages work anytime, even during cooldown!)
        session = ConversationService.get_or_create_active_session(
            db=db,
            device_id=device_id,
            session_id=session_id,
            trigger_type="user_initiated"
        )

        # 2. Persist user turn
        user_message = ConversationMessage(
            session_id=session.id,
            role="user",
            content=message_text.strip(),
            delivery_status="delivered",
            created_at=now_utc
        )
        db.add(user_message)
        db.commit()
        db.refresh(user_message)

        # 3. Assemble history (sliding window: last 8 messages)
        history_records = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session.id)
            .order_by(ConversationMessage.id.asc())
            .all()
        )

        formatted_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in history_records[-8:]
            if msg.content and msg.content.strip()
        ]

        # 4. Build prompt with structured context + RAG
        system_prompt = ConversationService.build_system_prompt(
            db=db,
            device_id=device_id,
            user_query=message_text
        )

        # 5. Call Groq LLM
        reply_text = LLMService.generate_response(
            messages=formatted_messages,
            system_prompt=system_prompt
        )

        # 6. Persist assistant turn
        assistant_message = ConversationMessage(
            session_id=session.id,
            role="assistant",
            content=reply_text,
            delivery_status="delivered",
            created_at=datetime.now(timezone.utc)
        )
        db.add(assistant_message)
        db.commit()

        # 7. Asynchronous memory extraction heuristic (e.g., if user shares clear preference/fact)
        ConversationService._extract_memory_if_eligible(
            db=db,
            text=message_text,
            session_id=session.id,
            message_id=user_message.id
        )

        # 8. If MQTT publisher provided, publish voice/TTS command to ESP32
        if mqtt_publisher:
            try:
                mqtt_publisher.publish_command(
                    device_id=device_id,
                    command_type="speak",
                    payload={"text": reply_text, "session_id": session.id}
                )
            except Exception:
                pass

        return SendMessageResponse(
            session_id=session.id,
            reply=reply_text,
            trigger_type=session.trigger_type,
            created_at=assistant_message.created_at
        )

    @staticmethod
    def _extract_memory_if_eligible(
        db: Session,
        text: str,
        session_id: str,
        message_id: int
    ) -> None:
        """
        Lightweight heuristic extractor for confirmed user facts/preferences.
        Never extracts mood signals or assistant assumptions.
        """
        lowered = text.lower()
        triggers = ["favorite", "i love", "i prefer", "exam", "test", "studying", "working on", "i dislike", "i really like"]
        for trig in triggers:
            if trig in lowered and len(text.strip()) > 10:
                # Save as confirmed user memory
                MemoryService.add_memory(
                    db=db,
                    content=text.strip(),
                    session_id=session_id,
                    message_id=message_id
                )
                break

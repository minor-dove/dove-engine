"""
Reminder Service.
Manages creation, persistent scheduling, delivery, retry logic, and acknowledgement.
Reminders run independently of proactive conversation cooldowns.
"""

from typing import List, Optional, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.reminder import Reminder
from app.schemas.reminder import ReminderCreate, ReminderUpdate


class ReminderService:
    @staticmethod
    def create_reminder(db: Session, reminder_in: ReminderCreate) -> Reminder:
        scheduled_utc = reminder_in.scheduled_time
        if scheduled_utc.tzinfo is None:
            scheduled_utc = scheduled_utc.replace(tzinfo=timezone.utc)

        reminder = Reminder(
            message=reminder_in.message.strip(),
            scheduled_time=scheduled_utc,
            status="pending",
            retry_count=0,
            created_at=datetime.now(timezone.utc)
        )
        db.add(reminder)
        db.commit()
        db.refresh(reminder)
        return reminder

    @staticmethod
    def get_reminder(db: Session, reminder_id: int) -> Optional[Reminder]:
        return db.query(Reminder).filter(Reminder.id == reminder_id).first()

    @staticmethod
    def list_reminders(
        db: Session,
        status: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> List[Reminder]:
        query = db.query(Reminder)
        if status:
            query = query.filter(Reminder.status == status)
        return query.order_by(Reminder.scheduled_time.asc()).offset(skip).limit(limit).all()

    @staticmethod
    def update_reminder(db: Session, reminder_id: int, reminder_in: ReminderUpdate) -> Optional[Reminder]:
        reminder = ReminderService.get_reminder(db, reminder_id)
        if not reminder:
            return None

        if reminder_in.message is not None:
            reminder.message = reminder_in.message.strip()
        if reminder_in.scheduled_time is not None:
            sch = reminder_in.scheduled_time
            if sch.tzinfo is None:
                sch = sch.replace(tzinfo=timezone.utc)
            reminder.scheduled_time = sch
        if reminder_in.status is not None:
            reminder.status = reminder_in.status.lower()

        db.commit()
        db.refresh(reminder)
        return reminder

    @staticmethod
    def acknowledge_reminder(db: Session, reminder_id: int) -> Optional[Reminder]:
        reminder = ReminderService.get_reminder(db, reminder_id)
        if not reminder:
            return None

        reminder.status = "acknowledged"
        reminder.acknowledged_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(reminder)
        return reminder

    @staticmethod
    def deliver_due_reminders(db: Session, mqtt_publisher: Optional[Any] = None) -> List[Reminder]:
        """
        Finds all pending or retrying reminders that are due.
        Delivers via MQTT, tracks attempts, and applies safe retry on failure.
        """
        now_utc = datetime.now(timezone.utc)
        due_reminders = db.query(Reminder).filter(
            Reminder.status.in_(["pending", "retrying"]),
            Reminder.scheduled_time <= now_utc
        ).all()

        delivered_list = []
        for reminder in due_reminders:
            reminder.last_attempt_at = now_utc
            try:
                if mqtt_publisher:
                    mqtt_publisher.publish_command(
                        device_id="dove-esp32-01",
                        command_type="reminder_alert",
                        payload={
                            "reminder_id": reminder.id,
                            "message": reminder.message,
                            "scheduled_time": reminder.scheduled_time.isoformat()
                        }
                    )
                reminder.status = "delivered"
                delivered_list.append(reminder)
            except Exception:
                reminder.retry_count += 1
                if reminder.retry_count > 3:
                    reminder.status = "failed"
                else:
                    reminder.status = "retrying"
                    # Backoff retry by 2 minutes
                    reminder.scheduled_time = now_utc + timedelta(minutes=2)

        db.commit()
        return delivered_list

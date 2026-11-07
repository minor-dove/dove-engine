"""
Tasks, Reminders, and Routine Scheduling Tests.
Validates CRUD, delivery via MQTT, restart recovery, retry behavior,
and independence from proactive conversation cooldown.
"""

from datetime import datetime, timezone, timedelta

from app.services.task_service import TaskService
from app.services.reminder_service import ReminderService
from app.services.routine_service import RoutineService
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.reminder import ReminderCreate
from app.models.proactive import ProactiveCooldown
from app.models.routine import RoutineExecution
from app.core.security import ensure_utc


def test_task_lifecycle(db_session):
    """Test task creation, update, and completion."""
    task = TaskService.create_task(
        db=db_session,
        task_in=TaskCreate(title="Feed the fish", description="Morning feeding")
    )
    assert task.id is not None
    assert task.status == "pending"

    # Update to completed
    updated = TaskService.update_task(
        db=db_session,
        task_id=task.id,
        task_in=TaskUpdate(status="completed")
    )
    assert updated.status == "completed"

    # List tasks
    completed_tasks = TaskService.list_tasks(db=db_session, status="completed")
    assert len(completed_tasks) == 1
    assert completed_tasks[0].id == task.id


def test_reminder_delivery_independent_of_cooldown(db_session, mock_mqtt):
    """
    Reminders and task delivery must NOT be blocked by the proactive cooldown.
    """
    now = datetime.now(timezone.utc)

    # Set an active proactive cooldown
    cooldown = ProactiveCooldown(
        device_id="dove-esp32-01",
        last_proactive_at=now,
        cooldown_until=now + timedelta(minutes=28),
        last_trigger_type="mood_sad"
    )
    db_session.add(cooldown)
    db_session.commit()

    # Create due reminder
    reminder = ReminderService.create_reminder(
        db=db_session,
        reminder_in=ReminderCreate(
            message="Time to take medicine",
            scheduled_time=now - timedelta(seconds=10)
        )
    )

    # Trigger delivery
    delivered = ReminderService.deliver_due_reminders(db_session, mqtt_publisher=mock_mqtt)

    assert len(delivered) == 1
    assert delivered[0].id == reminder.id
    assert delivered[0].status == "delivered"
    assert len(mock_mqtt.published_commands) == 1
    assert mock_mqtt.published_commands[0]["command_type"] == "reminder_alert"


def test_reminder_failure_and_retry(db_session):
    """
    When delivery fails, retry_count increments and reminder status moves to retrying.
    """
    now = datetime.now(timezone.utc)
    reminder = ReminderService.create_reminder(
        db=db_session,
        reminder_in=ReminderCreate(
            message="Test retry on failure",
            scheduled_time=now - timedelta(seconds=10)
        )
    )

    class FailingMQTTPublisher:
        def publish_command(self, *args, **kwargs):
            raise ConnectionError("Broker unreachable")

    ReminderService.deliver_due_reminders(db_session, mqtt_publisher=FailingMQTTPublisher())

    db_session.refresh(reminder)
    assert reminder.retry_count == 1
    assert reminder.status == "retrying"
    assert ensure_utc(reminder.scheduled_time) > now  # backed off into future

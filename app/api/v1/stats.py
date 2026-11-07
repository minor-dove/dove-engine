"""
User and Device Statistics API Router.
Provides aggregated analytics on conversations, task completions, reminders, routines, and mood history.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.deps import get_database
from app.models.conversation import ConversationSession, ConversationMessage
from app.models.task import TaskItem
from app.models.reminder import Reminder
from app.models.routine import RoutineExecution
from app.models.mood import MoodEvent
from app.schemas.stats import (
    UserStatisticsResponse,
    ConversationStats,
    TaskStats,
    ReminderStats,
    RoutineStats
)

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("", response_model=UserStatisticsResponse)
def get_user_statistics(db: Session = Depends(get_database)):
    """
    Returns aggregated companion and user statistics.
    """
    # 1. Conversations
    total_sessions = db.query(ConversationSession).count()
    active_sessions = db.query(ConversationSession).filter(ConversationSession.is_active.is_(True)).count()
    total_messages = db.query(ConversationMessage).count()
    false_triggers = db.query(ConversationSession).filter(ConversationSession.is_false_trigger.is_(True)).count()

    conv_stats = ConversationStats(
        total_sessions=total_sessions,
        active_sessions=active_sessions,
        total_messages=total_messages,
        false_triggers=false_triggers
    )

    # 2. Tasks
    total_tasks = db.query(TaskItem).count()
    pending_tasks = db.query(TaskItem).filter(TaskItem.status == "pending").count()
    completed_tasks = db.query(TaskItem).filter(TaskItem.status == "completed").count()
    cancelled_tasks = db.query(TaskItem).filter(TaskItem.status == "cancelled").count()
    completion_rate = (completed_tasks / total_tasks * 100.0) if total_tasks > 0 else 0.0

    task_stats = TaskStats(
        total=total_tasks,
        pending=pending_tasks,
        completed=completed_tasks,
        cancelled=cancelled_tasks,
        completion_rate_pct=round(completion_rate, 1)
    )

    # 3. Reminders
    total_reminders = db.query(Reminder).count()
    pending_reminders = db.query(Reminder).filter(Reminder.status == "pending").count()
    delivered_reminders = db.query(Reminder).filter(Reminder.status == "delivered").count()
    acknowledged_reminders = db.query(Reminder).filter(Reminder.status == "acknowledged").count()
    failed_reminders = db.query(Reminder).filter(Reminder.status == "failed").count()

    reminder_stats = ReminderStats(
        total=total_reminders,
        pending=pending_reminders,
        delivered=delivered_reminders,
        acknowledged=acknowledged_reminders,
        failed=failed_reminders
    )

    # 4. Routines
    total_routines = db.query(RoutineExecution).count()
    last_routine = db.query(RoutineExecution).order_by(RoutineExecution.executed_at.desc()).first()

    routine_stats = RoutineStats(
        total_executed=total_routines,
        last_routine_type=last_routine.routine_type if last_routine else None,
        last_routine_time=last_routine.executed_at if last_routine else None
    )

    # 5. Mood Distribution
    mood_counts = (
        db.query(MoodEvent.emotion, func.count(MoodEvent.id))
        .filter(MoodEvent.is_valid.is_(True))
        .group_by(MoodEvent.emotion)
        .all()
    )
    mood_distribution = {emotion: count for emotion, count in mood_counts}

    return UserStatisticsResponse(
        conversations=conv_stats,
        tasks=task_stats,
        reminders=reminder_stats,
        routines=routine_stats,
        mood_distribution=mood_distribution
    )

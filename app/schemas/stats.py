"""
User and companion statistics schemas.
"""

from typing import Dict, Optional
from datetime import datetime
from pydantic import BaseModel


class ConversationStats(BaseModel):
    total_sessions: int
    active_sessions: int
    total_messages: int
    false_triggers: int


class TaskStats(BaseModel):
    total: int
    pending: int
    completed: int
    cancelled: int
    completion_rate_pct: float


class ReminderStats(BaseModel):
    total: int
    pending: int
    delivered: int
    acknowledged: int
    failed: int


class RoutineStats(BaseModel):
    total_executed: int
    last_routine_type: Optional[str] = None
    last_routine_time: Optional[datetime] = None


class UserStatisticsResponse(BaseModel):
    conversations: ConversationStats
    tasks: TaskStats
    reminders: ReminderStats
    routines: RoutineStats
    mood_distribution: Dict[str, int]

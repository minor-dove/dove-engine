"""
API v1 Router.
Aggregates all domain sub-routers into a unified versioned API prefix (/api/v1).
"""

from fastapi import APIRouter

from app.api.v1.conversations import router as conversations_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.reminders import router as reminders_router
from app.api.v1.preferences import router as preferences_router
from app.api.v1.routines import router as routines_router
from app.api.v1.memories import router as memories_router
from app.api.v1.devices import router as devices_router
from app.api.v1.stats import router as stats_router
from app.api.v1.mood import router as mood_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(conversations_router)
api_v1_router.include_router(tasks_router)
api_v1_router.include_router(reminders_router)
api_v1_router.include_router(preferences_router)
api_v1_router.include_router(routines_router)
api_v1_router.include_router(memories_router)
api_v1_router.include_router(devices_router)
api_v1_router.include_router(stats_router)
api_v1_router.include_router(mood_router)

"""
Main FastAPI Application Entrypoint.
Initializes lifespan handlers, CORS, API v1 routes, and health monitoring.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings
from app.core.init_db import init_db
from app.core.database import get_db
from app.api.v1.router import api_v1_router
from app.api.ws_audio import router as ws_audio_router
from app.mqtt.client import mqtt_service
from app.services.scheduler import AppScheduler

# Scheduler instance
app_scheduler = AppScheduler(mqtt_publisher=mqtt_service)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle manager:
    Initializes database tables, connects MQTT client, and starts background scheduler.
    """
    if settings.APP_ENV != "test":
        # 1. Initialize DB schema and seed default starters/preferences
        init_db()

        # 2. Start MQTT network loop (tolerates offline broker gracefully)
        mqtt_service.start()

        # 3. Start persistent scheduler (only in the process that owns planning: the worker in Docker)
        if settings.RUN_SCHEDULER:
            app_scheduler.start()

    yield

    # Teardown
    if settings.APP_ENV != "test":
        app_scheduler.shutdown()
        mqtt_service.stop()


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Production-conscious backend for DOVE, an AI-powered desk pet. "
        "Provides mood-aware conversations, deterministic triggers, long-term memory, "
        "tasks, reminders, and daily routines."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for local companion app access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local development setting
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include versioned API router
app.include_router(api_v1_router)
app.include_router(ws_audio_router)


@app.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """
    System health check.
    Validates application readiness, database connectivity, and MQTT broker state.
    """
    db_status = "unhealthy"
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "database": db_status,
        "mqtt_connected": mqtt_service.is_connected
    }


@app.get("/", tags=["Root"])
def root_redirect():
    """Root redirect with service metadata."""
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "docs_url": "/docs",
        "health_url": "/health"
    }

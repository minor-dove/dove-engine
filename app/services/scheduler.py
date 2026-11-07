"""
Persistent Background Scheduler.
Periodically polls database to deliver due reminders and plan stress sessions.
Automatically recovers pending reminders after system restart without duplicate delivery.
"""

import logging
from typing import Optional, Any
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.reminder_service import ReminderService
from app.services.stress_planner import StressPlanner

logger = logging.getLogger(__name__)


class AppScheduler:
    def __init__(self, mqtt_publisher: Optional[Any] = None):
        self.scheduler = BackgroundScheduler()
        self.mqtt_publisher = mqtt_publisher
        self.is_running = False

    def _tick(self):
        """Single tick of the background scheduler: checks reminders and routines."""
        db = SessionLocal()
        try:
            # 1. Recover and deliver due reminders
            delivered = ReminderService.deliver_due_reminders(db, mqtt_publisher=self.mqtt_publisher)
            if delivered:
                logger.info(f"Delivered {len(delivered)} due reminders.")

            # 2. Presence-based stress sessions (replaces the old chatty daily routines)
            started = StressPlanner.run(db, mqtt_publisher=self.mqtt_publisher)
            if started:
                logger.info(f"Started stress sessions for: {started}")
        except Exception as e:
            logger.error(f"Error in scheduler tick: {type(e).__name__}: {str(e)}")
        finally:
            db.close()

    def start(self):
        """Starts the persistent background scheduler."""
        if not self.is_running:
            self.scheduler.add_job(
                self._tick,
                trigger=IntervalTrigger(seconds=settings.SCHEDULER_CHECK_INTERVAL_SECONDS),
                id="dove_main_tick",
                replace_existing=True
            )
            self.scheduler.start()
            self.is_running = True
            logger.info("Project DOVE persistent scheduler started.")
            # Run an immediate tick on startup to recover any missed reminders from restart
            self._tick()

    def shutdown(self):
        """Gracefully stops the scheduler."""
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("Project DOVE persistent scheduler shut down.")

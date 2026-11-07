"""
Project DOVE Background Worker Process.
Runs the MQTT consumer and the persistent scheduler for reminders and routines.
"""

import logging
import signal
import sys
import time

from app.core.config import settings
from app.core.init_db import init_db
from app.mqtt.client import mqtt_service
from app.services.scheduler import AppScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("dove.worker")

running = True


def signal_handler(sig, frame):
    global running
    logger.info("Worker received shutdown signal. Terminating gracefully...")
    running = False


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting DOVE Background Worker...")

    # Ensure database tables and initial seeds exist
    init_db()

    # Start MQTT loop
    mqtt_service.start()

    # Start persistent scheduler
    scheduler = AppScheduler(mqtt_publisher=mqtt_service)
    scheduler.start()

    logger.info("DOVE Background Worker is running. Waiting for events...")

    while running:
        time.sleep(1)

    # Cleanup
    scheduler.shutdown()
    mqtt_service.stop()
    logger.info("Worker shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()

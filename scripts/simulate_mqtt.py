"""
DOVE — device simulator (in-process, no broker needed). Exercises the same handlers the worker uses:
emotion event, presence, privacy (DND), and a full stress session driven by the planner.

Run: python scripts/simulate_mqtt.py   (uses DATABASE_URL; set GROQ_API_KEY for the real LLM)
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, Base, engine
from app.core.init_db import init_db
import app.models  # noqa: F401
from app.mqtt.handlers import handle_incoming_mood_event, handle_incoming_presence, handle_incoming_privacy
from app.models.preference import UserPreference
from app.services.stress_planner import StressPlanner
from app.services.stress_service import StressService


class Pub:
    def publish_command(self, device_id, command_type, payload):
        print(f"   [-> device] {command_type}: {json.dumps(payload)[:140]}")
        return True


def main():
    Base.metadata.create_all(engine)
    init_db()
    dev = f"dove-sim-{uuid.uuid4().hex[:6]}"
    t = f"dove/devices/{dev}"
    pub = Pub()

    db = SessionLocal()
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    pref.quiet_hours_start = pref.quiet_hours_end = "03:00"   # simulate regardless of hour
    db.commit()

    print("1. emotion event (signal only)")
    ev = {"event_id": uuid.uuid4().hex, "mood_id": 4, "recorded_at": datetime.now(timezone.utc).isoformat()}
    print("  ", handle_incoming_mood_event(f"{t}/events", json.dumps(ev).encode(), pub)["status"])

    print("2. privacy ON -> events dropped, no sessions")
    handle_incoming_privacy(f"{t}/privacy", b'{"mode":"on"}', pub)
    ev["event_id"] = uuid.uuid4().hex
    print("  ", handle_incoming_mood_event(f"{t}/events", json.dumps(ev).encode(), pub))
    handle_incoming_privacy(f"{t}/privacy", b'{"mode":"off"}', pub)

    print("3. presence + planner (force window open for the demo)")
    from app.core.config import settings
    settings.STRESS_DAY_START, settings.STRESS_DAY_END, settings.STRESS_PRESENCE_SETTLE_SECONDS = "00:00", "23:59", 0
    handle_incoming_presence(f"{t}/presence", b'{"present":true}')
    print("   started:", StressPlanner.run(db, mqtt_publisher=pub))

    print("4. answer the session")
    from app.models.stress import StressSession
    s = db.query(StressSession).filter_by(device_id=dev, status="active").one()
    for ans in ["sometimes", "a little", "fairly often", "not at all", "sometimes"]:
        r = StressService.submit_answer(db, s.id, ans, mqtt_publisher=pub)
    print("   score:", r["score"], r["band"], r["status"])
    print("   day:", StressService.day_report(db, dev, r["local_date"]))


if __name__ == "__main__":
    main()

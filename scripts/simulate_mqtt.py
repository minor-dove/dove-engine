"""
DOVE Project — MQTT Input Simulator & Validator.
Tests all MQTT edge topics:
1. Valid Mood Event (dove/devices/{id}/events)
2. Privacy Violation Rejection (verifies forbidden camera/image keys are dropped)
3. 10-Consecutive Mood Streak (verifies qualifying proactive check-in trigger)
4. Device Status Heartbeat (dove/devices/{id}/status)
5. Voice Message Transcript (dove/devices/{id}/conversation/message)
"""

import sys
import os
import json
from datetime import datetime, timezone, timedelta

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.mqtt.handlers import (
    handle_incoming_mood_event,
    handle_incoming_device_status,
    handle_incoming_voice_message
)
from app.models.preference import UserPreference
from app.models.conversation import ConversationSession


class MockMqttPublisher:
    """Mock publisher to capture commands sent back to the ESP32."""
    def __init__(self):
        self.published_commands = []

    def publish_command(self, device_id: str, command_type: str, payload: dict):
        self.published_commands.append({
            "device_id": device_id,
            "command_type": command_type,
            "payload": payload
        })
        print(f"   [MQTT COMMAND OUT] Sent '{command_type}' to device '{device_id}':")
        print(f"      {json.dumps(payload, indent=6)}")


def run_tests():
    print("=" * 70)
    print(" PROJECT DOVE — MQTT INPUT TEST SUITE")
    print("=" * 70)

    import uuid
    run_id = uuid.uuid4().hex[:6]
    device_id = f"dove-sim-{run_id}"
    publisher = MockMqttPublisher()

    # Disable quiet hours temporarily for this test so proactive check-in can trigger at any hour
    db = SessionLocal()
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    if pref:
        pref.quiet_hours_start = "03:00"
        pref.quiet_hours_end = "03:00"
        db.commit()
    db.close()

    # ---------------------------------------------------------
    # TEST 1: Single Valid Mood Event
    # ---------------------------------------------------------
    print("\n--- TEST 1: Ingesting Single Valid Mood Event (Sad: mood_id=4) ---")
    topic_events = f"dove/devices/{device_id}/events"
    now_utc = datetime.now(timezone.utc)
    payload_1 = {
        "event_id": f"{run_id}-evt-001",
        "device_id": device_id,
        "mood_id": 4,  # Sad
        "recorded_at": (now_utc - timedelta(minutes=15)).isoformat()
    }
    raw_1 = json.dumps(payload_1).encode("utf-8")
    res_1 = handle_incoming_mood_event(topic_events, raw_1, mqtt_publisher=publisher)
    print(f"Result Status : {res_1.get('status')}")
    print(f"Emotion       : {res_1.get('emotion')}")
    print(f"Current Streak: {res_1.get('streak', {}).get('count')}")
    print(f"Outcome Action: {res_1.get('trigger_outcome', {}).get('action')}")
    assert res_1.get("status") == "processed"
    print("✅ TEST 1 PASSED: Valid mood event ingested and streak started.")

    # ---------------------------------------------------------
    # TEST 2: Privacy Guard (Strict Camera / Image Rejection)
    # ---------------------------------------------------------
    print("\n--- TEST 2: Privacy Guard Violation Rejection ---")
    payload_violation = {
        "event_id": f"{run_id}-evt-privacy-violation",
        "device_id": device_id,
        "mood_id": 0,
        "image": "base64_raw_pixel_buffer_from_camera...",  # FORBIDDEN KEY
        "recorded_at": now_utc.isoformat()
    }
    raw_viol = json.dumps(payload_violation).encode("utf-8")
    res_viol = handle_incoming_mood_event(topic_events, raw_viol, mqtt_publisher=publisher)
    print(f"Result Status : {res_viol.get('status')}")
    print(f"Reason        : {res_viol.get('reason')}")
    print(f"Detail        : {res_viol.get('detail')}")
    assert res_viol.get("status") == "rejected"
    print("✅ TEST 2 PASSED: Privacy violation was immediately dropped and rejected.")

    # ---------------------------------------------------------
    # TEST 3: Sustained 10-Consecutive Mood Events -> Proactive Trigger
    # ---------------------------------------------------------
    print("\n--- TEST 3: Sustained 10-Consecutive Streak Check-in ---")
    streak_base = now_utc - timedelta(minutes=11)
    for i in range(1, 10):
        evt_payload = {
            "event_id": f"{run_id}-streak-{i:03d}",
            "device_id": device_id,
            "mood_id": 4,  # Sad
            "recorded_at": (streak_base + timedelta(minutes=i)).isoformat()
        }
        res_i = handle_incoming_mood_event(topic_events, json.dumps(evt_payload).encode("utf-8"), mqtt_publisher=publisher)
        print(f"   Event {i}/10: streak count = {res_i.get('streak', {}).get('count')} (action: {res_i.get('trigger_outcome', {}).get('action')})")

    # 10th Event
    evt_10 = {
        "event_id": f"{run_id}-streak-010",
        "device_id": device_id,
        "mood_id": 4,  # Sad
        "recorded_at": (streak_base + timedelta(minutes=10)).isoformat()
    }
    res_10 = handle_incoming_mood_event(topic_events, json.dumps(evt_10).encode("utf-8"), mqtt_publisher=publisher)
    outcome = res_10.get("trigger_outcome", {})
    print(f"\n10th Event Outcome Action : {outcome.get('action')}")
    print(f"Starter Check-In Message  : \"{outcome.get('starter_text')}\"")
    print(f"Session Created           : {outcome.get('session_id')}")
    assert outcome.get("action") == "initiated"
    print("✅ TEST 3 PASSED: 10th consecutive Sad event triggered proactive check-in & speak command.")

    # ---------------------------------------------------------
    # TEST 4: Device Heartbeat / Status
    # ---------------------------------------------------------
    print("\n--- TEST 4: ESP32 Device Heartbeat Status ---")
    topic_status = f"dove/devices/{device_id}/status"
    status_payload = {
        "name": "DOVE Physical Desk Pet (ESP32-S3)",
        "status": "online",
        "firmware_version": "v1.2.0"
    }
    res_status = handle_incoming_device_status(topic_status, json.dumps(status_payload).encode("utf-8"))
    print(f"Device Status Update: {res_status}")
    assert res_status.get("status") == "updated"
    print("✅ TEST 4 PASSED: Device heartbeat recorded.")

    # ---------------------------------------------------------
    # TEST 5: ESP32 Speech Transcript / Voice Utterance
    # ---------------------------------------------------------
    print("\n--- TEST 5: ESP32 Speech-To-Text Transcription Utterance ---")
    topic_convo = f"dove/devices/{device_id}/conversation/message"
    convo_payload = {
        "message": "Hey Dove, I've had a busy morning. Can you say something encouraging?"
    }
    res_convo = handle_incoming_voice_message(topic_convo, json.dumps(convo_payload).encode("utf-8"), mqtt_publisher=publisher)
    print(f"Conversation Session : {res_convo.get('session_id')}")
    print(f"DOVE Assistant Reply : \"{res_convo.get('reply')}\"")
    assert res_convo.get("status") == "success"
    print("✅ TEST 5 PASSED: Voice transcription processed and empathetic AI response returned.")

    print("\n" + "=" * 70)
    print(" ALL 5 MQTT INPUT TESTS PASSED PERFECTLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()

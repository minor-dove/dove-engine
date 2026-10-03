"""
Privacy Guard Tests.
Validates that camera images, video, face embeddings, or raw sensor frames
are strictly rejected and never accepted or stored on the backend.
"""

import json
import pytest
from datetime import datetime, timezone

from app.core.security import inspect_payload_for_privacy_violation, PrivacyViolationError
from app.mqtt.handlers import handle_incoming_mood_event
from app.models.mood import MoodEvent


def test_inspect_payload_rejects_camera_keys():
    """Verify inspection raises PrivacyViolationError for forbidden camera keys."""
    forbidden_samples = [
        {"event_id": "e1", "image": "base64encodedimage..."},
        {"event_id": "e2", "frame": "raw_pixel_buffer"},
        {"event_id": "e3", "camera": {"resolution": "1080p"}},
        {"event_id": "e4", "face_embedding": [0.12, 0.45, 0.89]},
        {"event_id": "e5", "metadata": {"b64": "jpeg_data"}},
        {"event_id": "e6", "video": "stream_url"},
    ]

    for sample in forbidden_samples:
        with pytest.raises(PrivacyViolationError):
            inspect_payload_for_privacy_violation(sample)


def test_inspect_payload_allows_valid_classification():
    """Verify that pure mood ID and metadata payload passes inspection."""
    valid_payload = {
        "event_id": "evt-12345",
        "device_id": "dove-esp32-01",
        "mood_id": 4,
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }
    # Should not raise
    inspect_payload_for_privacy_violation(valid_payload)


def test_mqtt_handler_rejects_camera_payload(db_session):
    """Verify MQTT handler rejects incoming message containing camera/image keys."""
    topic = "dove/devices/dove-esp32-01/events"
    violating_payload = {
        "event_id": "evt-violating-01",
        "device_id": "dove-esp32-01",
        "mood_id": 0,
        "image": "raw_jpeg_bytes_here",
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }
    raw_bytes = json.dumps(violating_payload).encode("utf-8")

    result = handle_incoming_mood_event(topic, raw_bytes)
    assert result["status"] == "rejected"
    assert "privacy_violation" in result.get("reason", "") or "detail" in result

    # Assert no event was written to the database
    event_in_db = db_session.query(MoodEvent).filter(MoodEvent.event_id == "evt-violating-01").first()
    assert event_in_db is None

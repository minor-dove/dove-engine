"""
MQTT Event Handlers.
Processes incoming MQTT messages, decodes payloads, validates schemas,
and delegates to TriggerEngine and ConversationService.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.core.database import SessionLocal
from app.core.security import PrivacyViolationError
from app.schemas.mood import MoodEventCreate
from app.services.trigger_engine import TriggerEngine
from app.services.conversation_service import ConversationService
from app.models.device import Device

logger = logging.getLogger(__name__)


def handle_incoming_mood_event(topic: str, payload_bytes: bytes, mqtt_publisher: Optional[Any] = None) -> Dict[str, Any]:
    """
    Handles mood classification event received from an ESP32 device.
    Topic pattern: dove/devices/{device_id}/events
    """
    try:
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Malformed JSON on topic {topic}: {e}")
        return {"status": "error", "reason": "invalid_json"}

    # Extract device_id from topic
    parts = topic.strip("/").split("/")
    if len(parts) >= 3:
        topic_device_id = parts[2]
    else:
        topic_device_id = "unknown"

    # Ensure device_id in payload matches or is set
    if "device_id" not in data:
        data["device_id"] = topic_device_id

    # Parse recorded_at timestamp
    if "recorded_at" in data and isinstance(data["recorded_at"], str):
        try:
            data["recorded_at"] = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
        except Exception:
            data["recorded_at"] = datetime.now(timezone.utc)
    elif "recorded_at" not in data:
        data["recorded_at"] = datetime.now(timezone.utc)

    # Validate schema
    try:
        event_obj = MoodEventCreate(**data)
    except PrivacyViolationError as pve:
        logger.critical(f"PRIVACY VIOLATION on topic {topic}: {pve}")
        return {"status": "rejected", "reason": "privacy_violation", "detail": str(pve)}
    except Exception as val_err:
        logger.warning(f"Invalid mood event payload on {topic}: {val_err}")
        return {"status": "rejected", "reason": "validation_error", "detail": str(val_err)}

    # Process with TriggerEngine
    db = SessionLocal()
    try:
        result = TriggerEngine.ingest_mood_event(db, event_obj)
        
        # If trigger initiated a proactive check-in, publish speech command to ESP32
        if result.get("trigger_outcome", {}).get("action") == "initiated" and mqtt_publisher:
            outcome = result["trigger_outcome"]
            mqtt_publisher.publish_command(
                device_id=event_obj.device_id,
                command_type="speak",
                payload={
                    "text": outcome["starter_text"],
                    "session_id": outcome["session_id"],
                    "trigger_type": outcome["trigger_type"]
                }
            )
        return result
    except PrivacyViolationError as pve:
        logger.critical(f"Privacy violation detected during processing: {pve}")
        return {"status": "rejected", "reason": "privacy_violation"}
    except Exception as e:
        logger.error(f"Error processing mood event: {type(e).__name__}: {e}")
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


def handle_incoming_device_status(topic: str, payload_bytes: bytes) -> Dict[str, Any]:
    """
    Handles heartbeat and connectivity updates from ESP32.
    Topic pattern: dove/devices/{device_id}/status
    """
    try:
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        data = {}

    parts = topic.strip("/").split("/")
    device_id = parts[2] if len(parts) >= 3 else "unknown"

    db = SessionLocal()
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            device = Device(
                id=device_id,
                name=data.get("name", "DOVE Desk Pet"),
                status=data.get("status", "online"),
                firmware_version=data.get("firmware_version"),
                last_seen_at=datetime.now(timezone.utc)
            )
            db.add(device)
        else:
            device.status = data.get("status", "online")
            if "firmware_version" in data:
                device.firmware_version = data["firmware_version"]
            device.last_seen_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "updated", "device_id": device_id}
    except Exception as e:
        logger.error(f"Error updating device status: {e}")
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


def handle_incoming_voice_message(topic: str, payload_bytes: bytes, mqtt_publisher: Optional[Any] = None) -> Dict[str, Any]:
    """
    Handles speech/text transcription sent by ESP32 after on-device wake-word detection.
    Topic pattern: dove/devices/{device_id}/conversation/message
    """
    try:
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Malformed JSON conversation message on {topic}: {e}")
        return {"status": "error", "reason": "invalid_json"}

    parts = topic.strip("/").split("/")
    device_id = parts[2] if len(parts) >= 3 else "dove-esp32-01"

    message_text = data.get("message", "").strip()
    session_id = data.get("session_id")

    if not message_text:
        return {"status": "ignored", "reason": "empty_message"}

    db = SessionLocal()
    try:
        response = ConversationService.handle_user_message(
            db=db,
            device_id=device_id,
            message_text=message_text,
            session_id=session_id,
            mqtt_publisher=mqtt_publisher
        )
        return {"status": "success", "session_id": response.session_id, "reply": response.reply}
    except Exception as e:
        logger.error(f"Error handling conversation message: {e}")
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()

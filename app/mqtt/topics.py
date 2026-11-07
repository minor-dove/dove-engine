"""
MQTT Topic Definitions for Project DOVE.
Standardized and versioned topic conventions for ESP32 hardware communication.
"""

# Base topic prefix
TOPIC_BASE = "dove/devices"

# Incoming telemetry / events (e.g. mood classification observations)
TOPIC_EVENTS_SUB = "dove/devices/+/events"
TOPIC_EVENTS = "dove/devices/{device_id}/events"

# Incoming device connectivity / heartbeat
TOPIC_STATUS_SUB = "dove/devices/+/status"
TOPIC_STATUS = "dove/devices/{device_id}/status"

# Incoming user conversation speech transcript (wake-word triggered on ESP32)
TOPIC_CONVERSATION_SUB = "dove/devices/+/conversation/message"
TOPIC_CONVERSATION = "dove/devices/{device_id}/conversation/message"

# Outgoing commands from backend to ESP32 (TTS speech, reminder alerts, actions)
TOPIC_COMMANDS = "dove/devices/{device_id}/commands"

# Presence (user in front of the device) and privacy mode (DND). Privacy is retained, QoS 1.
TOPIC_PRESENCE_SUB = "dove/devices/+/presence"
TOPIC_PRIVACY_SUB = "dove/devices/+/privacy"

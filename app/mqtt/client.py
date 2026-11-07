"""
MQTT Client Service.
Manages connections to Eclipse Mosquitto broker, topic subscriptions,
automatic reconnects, and command dispatching to ESP32 hardware.
"""

import json
import logging
import time
from typing import Optional, Dict, Any
import paho.mqtt.client as mqtt

from app.core.config import settings
from app.mqtt.topics import TOPIC_EVENTS_SUB, TOPIC_STATUS_SUB, TOPIC_CONVERSATION_SUB, TOPIC_COMMANDS
from app.mqtt.handlers import handle_incoming_mood_event, handle_incoming_device_status, handle_incoming_voice_message

logger = logging.getLogger(__name__)


class MQTTService:
    def __init__(self):
        # Using CallbackAPIVersion.VERSION2 for paho-mqtt 2.x
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.MQTT_CLIENT_ID
        )
        self.is_connected = False

        # Register callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.is_connected = True
            logger.info(f"Connected to Mosquitto MQTT broker at {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")
            # Subscribe to all device events and messages
            client.subscribe(TOPIC_EVENTS_SUB, qos=1)
            client.subscribe(TOPIC_STATUS_SUB, qos=1)
            client.subscribe(TOPIC_CONVERSATION_SUB, qos=1)
            logger.info("Subscribed to DOVE device topics.")
        else:
            self.is_connected = False
            logger.warning(f"Failed to connect to MQTT broker, return code: {rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.is_connected = False
        logger.warning(f"Disconnected from MQTT broker (rc={rc}). Will attempt reconnection.")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload
        logger.debug(f"Received MQTT message on topic: {topic}")

        try:
            if topic.endswith("/events"):
                handle_incoming_mood_event(topic, payload, mqtt_publisher=self)
            elif topic.endswith("/status"):
                handle_incoming_device_status(topic, payload)
            elif "/conversation/message" in topic:
                handle_incoming_voice_message(topic, payload, mqtt_publisher=self)
        except Exception as e:
            logger.error(f"Error handling message on {topic}: {e}")

    def publish_command(self, device_id: str, command_type: str, payload: Dict[str, Any]) -> bool:
        """
        Publishes a command to the ESP32 device on its dedicated command topic.
        Topic: dove/devices/{device_id}/commands
        """
        topic = TOPIC_COMMANDS.format(device_id=device_id)
        message_dict = {
            "command": command_type,
            "timestamp": time.time(),
            "payload": payload
        }
        body = json.dumps(message_dict)

        if not self.is_connected:
            logger.warning(f"MQTT not connected; unable to deliver command '{command_type}' to {topic}")
            return False

        try:
            res = self.client.publish(topic, body, qos=1)
            return res.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Error publishing command to {topic}: {e}")
            return False

    def start(self):
        """Starts the MQTT network loop asynchronously."""
        try:
            logger.info(f"Connecting to MQTT broker at {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}...")
            self.client.connect_async(
                host=settings.MQTT_BROKER_HOST,
                port=settings.MQTT_BROKER_PORT,
                keepalive=settings.MQTT_KEEPALIVE
            )
            self.client.loop_start()
        except Exception as e:
            logger.warning(f"Could not connect to MQTT broker ({e}). Continuing in standalone mode.")

    def stop(self):
        """Stops the MQTT client loop."""
        try:
            self.client.loop_stop()
            self.client.disconnect()
            self.is_connected = False
            logger.info("MQTT client disconnected.")
        except Exception as e:
            logger.error(f"Error stopping MQTT client: {e}")


# Singleton instance
mqtt_service = MQTTService()

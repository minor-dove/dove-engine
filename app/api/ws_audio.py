"""WebSocket audio endpoint: /ws/audio/{device_id}. Protocol in app/voice/runner.py."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.mqtt.client import mqtt_service
from app.voice.runner import VoiceSessionRunner

logger = logging.getLogger(__name__)
router = APIRouter()


class WebSocketTransport:
    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def send_json(self, data: Dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(data))

    async def send_bytes(self, data: bytes) -> None:
        await self.ws.send_bytes(data)

    async def receive(self, timeout: float) -> Optional[Tuple[str, Any]]:
        msg = await asyncio.wait_for(self.ws.receive(), timeout)
        if msg["type"] == "websocket.disconnect":
            return None
        if msg.get("bytes") is not None:
            return ("bytes", msg["bytes"])
        try:
            return ("json", json.loads(msg.get("text") or "{}"))
        except ValueError:
            return ("json", {})


@router.websocket("/ws/audio/{device_id}")
async def ws_audio(ws: WebSocket, device_id: str):
    await ws.accept()
    runner = VoiceSessionRunner(WebSocketTransport(ws), device_id,
                                publisher=mqtt_service if mqtt_service.is_connected else None)
    try:
        await runner.run()
    except WebSocketDisconnect:
        logger.info(f"voice: {device_id} disconnected")
    except Exception as e:
        logger.error(f"voice: runner error for {device_id}: {type(e).__name__}: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass

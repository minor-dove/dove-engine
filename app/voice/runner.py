"""
Voice session runner: drives one spoken stress check-in over a WebSocket-like transport.

Wire protocol (/ws/audio/{device_id}); text frames are JSON, binary frames are PCM16LE mono @ AUDIO_SAMPLE_RATE.
  device -> server  {"type":"hello","device_id":..,"sample_rate":16000}   first message
                    binary PCM            only while the server has said "listen"
                    {"type":"speak_done"} playback finished
  server -> device  {"type":"speak_start","duration_ms":N,"sample_rate":R,"audio":true|false}
                    binary PCM (TTS)     then {"type":"speak_end"}
                    {"type":"listen","timeout_s":T} / {"type":"stop_listen"}
                    {"type":"session_end","score":S|null} / {"type":"error","reason":..}
If TTS is unavailable the server still sends speak_start with audio:false and the estimated duration,
so the device animates the mouth (text-only fallback).
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.conversation import ConversationMessage
from app.models.stress import StressSession
from app.services import speech_service
from app.services.device_state_service import DeviceStateService
from app.services.stress_service import StressService
from app.voice.vad import EnergyVAD

logger = logging.getLogger(__name__)

CHUNK_BYTES = 2048
HELLO_TIMEOUT_S = 10.0


class Transport:
    """Minimal duck-typed interface (implemented by the WebSocket adapter and by test fakes)."""
    async def send_json(self, data: Dict[str, Any]) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def receive(self, timeout: float) -> Optional[Tuple[str, Any]]:
        """-> ("json", dict) | ("bytes", bytes) | None on disconnect. Raises asyncio.TimeoutError."""


class VoiceSessionRunner:
    def __init__(self, transport: Transport, device_id: str, publisher: Optional[Any] = None,
                 db_factory: Callable = None, stt: Callable = None, tts: Callable = None):
        self.t = transport
        self.device_id = device_id
        self.publisher = publisher
        self.db_factory = db_factory or SessionLocal
        self.stt = stt or speech_service.transcribe
        self.tts = tts or speech_service.synthesize
        self.session_id: Optional[str] = None

    # ---- db helper: sync SQLAlchemy work runs in a thread ----
    async def _db(self, fn: Callable):
        def call():
            db = self.db_factory()
            try:
                return fn(db)
            finally:
                db.close()
        return await run_in_threadpool(call)

    async def _privacy(self) -> bool:
        return await self._db(lambda db: DeviceStateService.is_privacy_on(db, self.device_id))

    # ---- speaking ----
    async def speak(self, text: str) -> None:
        audio = await run_in_threadpool(self.tts, text) if text.strip() else None
        if audio:
            pcm, rate = audio
            ms = int(len(pcm) / 2 / rate * 1000)
            await self.t.send_json({"type": "speak_start", "duration_ms": ms, "sample_rate": rate, "audio": True})
            delay = (CHUNK_BYTES / 2 / rate) / settings.VOICE_SEND_PACE if settings.VOICE_SEND_PACE > 0 else 0
            for i in range(0, len(pcm), CHUNK_BYTES):
                await self.t.send_bytes(pcm[i:i + CHUNK_BYTES])
                if delay:
                    await asyncio.sleep(delay)
            await self.t.send_json({"type": "speak_end"})
            await self._wait_speak_done(ms / 1000.0 + 5.0)
        else:  # text-only fallback: device animates the mouth for an estimated duration
            ms = min(15000, max(1200, len(text) * 65))
            await self.t.send_json({"type": "speak_start", "duration_ms": ms, "sample_rate": 0, "audio": False})
            await asyncio.sleep(ms / 1000.0 / settings.VOICE_FALLBACK_SPEED)
            await self.t.send_json({"type": "speak_end"})

    async def _wait_speak_done(self, timeout: float) -> None:
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while True:
            remaining = end - loop.time()
            if remaining <= 0:
                return
            try:
                msg = await self.t.receive(remaining)
            except asyncio.TimeoutError:
                return
            if msg is None:
                raise ConnectionError("device disconnected")
            if msg[0] == "json" and msg[1].get("type") == "speak_done":
                return

    # ---- listening ----
    async def listen(self) -> Optional[bytes]:
        """Open the mic and return one utterance (PCM16), or None if the user said nothing."""
        vad = EnergyVAD()
        await self.t.send_json({"type": "listen",
                                "timeout_s": settings.VOICE_NO_SPEECH_TIMEOUT_S + settings.VOICE_MAX_UTTERANCE_S})
        loop = asyncio.get_event_loop()
        start = last_audio = loop.time()
        result: Optional[bytes] = None
        while True:
            now = loop.time()
            if not vad.started and now - start >= settings.VOICE_NO_SPEECH_TIMEOUT_S:
                break                                   # nobody spoke
            if vad.started and now - last_audio > 3.0:  # device went quiet mid-utterance: use what we have
                result = vad.audio()
                break
            try:
                msg = await self.t.receive(1.0)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                raise ConnectionError("device disconnected")
            if msg[0] == "bytes":
                last_audio = loop.time()
                if vad.feed(msg[1]):
                    result = vad.audio()
                    break
        await self.t.send_json({"type": "stop_listen"})
        return result

    # ---- main loop ----
    def _find_session(self, db):
        s = db.query(StressSession).filter(
            StressSession.device_id == self.device_id, StressSession.status == "active").first()
        if not s:
            return None
        last = db.query(ConversationMessage).filter(
            ConversationMessage.session_id == s.conversation_session_id,
            ConversationMessage.role == "assistant").order_by(ConversationMessage.id.desc()).first()
        return s.id, (last.content if last else "")

    async def run(self) -> None:
        try:
            msg = await self.t.receive(HELLO_TIMEOUT_S)
        except asyncio.TimeoutError:
            msg = None
        if not msg or msg[0] != "json" or msg[1].get("type") != "hello":
            await self.t.send_json({"type": "error", "reason": "hello_required"})
            return
        if await self._privacy():
            await self.t.send_json({"type": "error", "reason": "privacy_mode"})
            return
        found = await self._db(self._find_session)
        if not found:
            await self.t.send_json({"type": "error", "reason": "no_active_session"})
            return
        self.session_id, text = found
        misses = 0
        try:
            while True:
                if await self._privacy():
                    await self.t.send_json({"type": "error", "reason": "privacy_mode"})
                    return
                await self.speak(text)
                status = await self._db(lambda db: db.get(StressSession, self.session_id).status)
                if status != "active":
                    break
                if await self._privacy():
                    await self.t.send_json({"type": "error", "reason": "privacy_mode"})
                    return
                utterance = await self.listen()
                answer = await run_in_threadpool(self.stt, utterance, settings.AUDIO_SAMPLE_RATE) if utterance else None
                if not answer:
                    misses += 1
                    if misses >= settings.VOICE_MAX_MISSES:
                        await self._db(lambda db: StressService.abort_session(db, self.session_id, self.publisher))
                        await self.t.send_json({"type": "session_end", "score": None})
                        return
                    text = "Sorry, I didn't catch that. Could you say it again?"
                    continue
                misses = 0
                res = await self._db(lambda db: StressService.submit_answer(db, self.session_id, answer, self.publisher))
                text = res["question"] or ""
                if res["status"] != "active":
                    await self.speak(text)
                    await self.t.send_json({"type": "session_end", "score": res["score"]})
                    return
            score = await self._db(lambda db: db.get(StressSession, self.session_id).score)
            await self.t.send_json({"type": "session_end", "score": score})
        except ConnectionError:
            logger.warning(f"voice: device {self.device_id} disconnected mid-session (session stays active until it expires)")

"""Voice pipeline: audio utils, VAD, runner (fake device), WebSocket endpoint. STT/TTS are faked."""

import asyncio
import json
import math
import struct

import pytest

from app.core.config import settings
from app.models.stress import StressSession
from app.services import speech_service, stress_service
from app.services.device_state_service import DeviceStateService
from app.services.stress_service import StressService
from app.voice.audio import pcm_to_wav, resample, rms, wav_to_pcm
from app.voice.runner import VoiceSessionRunner
from app.voice.vad import EnergyVAD

DEV = "dove-esp32-01"
RATE = 16000


def tone(ms, amp=8000, hz=440):
    n = RATE * ms // 1000
    return struct.pack("<%dh" % n, *[int(amp * math.sin(2 * math.pi * hz * i / RATE)) for i in range(n)])


def silence(ms):
    return bytes(RATE * ms // 1000 * 2)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)
    monkeypatch.setattr(settings, "VOICE_SEND_PACE", 0)
    monkeypatch.setattr(settings, "VOICE_NO_SPEECH_TIMEOUT_S", 0.3)


# ---------- audio utils / VAD ----------
def test_wav_roundtrip_and_resample():
    pcm = tone(100)
    out, rate = wav_to_pcm(pcm_to_wav(pcm, RATE))
    assert out == pcm and rate == RATE
    r = resample(tone(300, hz=200), 24000 if False else RATE, 24000)
    assert abs(len(r) / 2 - RATE * 0.3 * 24000 / RATE) < 4
    down = resample(r, 24000, RATE)
    assert abs(len(down) - len(tone(300))) <= 4
    assert rms(tone(100)) > 4000 and rms(silence(100)) == 0


def test_vad_detects_utterance_and_ignores_silence():
    v = EnergyVAD()
    assert not v.feed(silence(500))
    assert v.feed(tone(600) + silence(1200))
    audio = v.audio()
    assert 0.5 < len(audio) / 2 / RATE < 1.6
    v2 = EnergyVAD()
    assert not v2.feed(silence(3000)) and not v2.started


def test_split_text():
    parts = speech_service.split_text("One. " * 80)
    assert all(len(p) <= 190 for p in parts) and len(parts) > 1


# ---------- runner with a fake device ----------
class FakeDevice:
    """Plays the device side: answers 'listen' with speech, 'speak_end' with speak_done."""

    def __init__(self, speak_with_audio=True, answers=True):
        self.inbox = asyncio.Queue()
        self.sent = []          # server -> device json
        self.audio_bytes = 0
        self.answers = answers
        self.inbox.put_nowait(("json", {"type": "hello", "device_id": DEV, "sample_rate": RATE}))

    async def send_json(self, d):
        self.sent.append(d)
        if d["type"] == "speak_end" and d is not None:
            self.inbox.put_nowait(("json", {"type": "speak_done"}))
        if d["type"] == "listen":
            if self.answers:
                self.inbox.put_nowait(("bytes", tone(600) + silence(1200)))
            # else: silence until server times out

    async def send_bytes(self, b):
        self.audio_bytes += len(b)

    async def receive(self, timeout):
        try:
            return await asyncio.wait_for(self.inbox.get(), timeout)
        except asyncio.TimeoutError:
            raise


def make_runner(db_session, dev, tts, stt):
    class _Shared:
        def __getattr__(self, n):
            return getattr(db_session, n)

        def close(self):
            pass
    return VoiceSessionRunner(dev, DEV, db_factory=lambda: _Shared(), stt=stt, tts=tts)


def fake_tts(text):
    return tone(200), RATE


def test_full_voice_session_completes(db_session):
    StressService.start_session(db_session, DEV)
    dev = FakeDevice()
    runner = make_runner(db_session, dev, fake_tts, lambda pcm, rate: "sometimes")
    asyncio.run(runner.run())
    types = [m["type"] for m in dev.sent]
    assert types[0] == "speak_start" and dev.sent[0]["audio"] is True
    assert types.count("listen") == 5 and types[-1] == "session_end"
    assert dev.sent[-1]["score"] is not None and dev.audio_bytes > 0
    s = db_session.query(StressSession).one()
    assert s.status == "completed"


def test_tts_unavailable_falls_back_to_timed_mouth(db_session, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_FALLBACK_SPEED", 1000)
    StressService.start_session(db_session, DEV)
    dev = FakeDevice()
    runner = make_runner(db_session, dev, lambda t: None, lambda pcm, rate: "a little")
    asyncio.run(runner.run())
    starts = [m for m in dev.sent if m["type"] == "speak_start"]
    assert starts and all(m["audio"] is False and m["duration_ms"] >= 1200 for m in starts)
    assert dev.sent[-1]["type"] == "session_end" and dev.sent[-1]["score"] is not None


def test_silence_twice_abandons_session(db_session):
    StressService.start_session(db_session, DEV)
    dev = FakeDevice(answers=False)
    runner = make_runner(db_session, dev, fake_tts, lambda pcm, rate: "x")
    asyncio.run(runner.run())
    assert dev.sent[-1] == {"type": "session_end", "score": None}
    assert db_session.query(StressSession).one().status == "aborted"


def test_privacy_blocks_voice(db_session):
    StressService.start_session(db_session, DEV)
    DeviceStateService.set_privacy(db_session, DEV, True)  # also aborts; start a fresh one is blocked by privacy
    dev = FakeDevice()
    asyncio.run(make_runner(db_session, dev, fake_tts, lambda p, r: "x").run())
    assert dev.sent[0] == {"type": "error", "reason": "privacy_mode"}


def test_no_active_session(db_session):
    dev = FakeDevice()
    asyncio.run(make_runner(db_session, dev, fake_tts, lambda p, r: "x").run())
    assert dev.sent[0] == {"type": "error", "reason": "no_active_session"}


def test_hello_required(db_session):
    dev = FakeDevice()
    dev.inbox = asyncio.Queue()
    dev.inbox.put_nowait(("json", {"type": "ping"}))
    asyncio.run(make_runner(db_session, dev, fake_tts, lambda p, r: "x").run())
    assert dev.sent[0]["reason"] == "hello_required"


# ---------- real WebSocket endpoint ----------
def test_websocket_endpoint(client, db_session, monkeypatch):
    class _Shared:
        def __getattr__(self, n):
            return getattr(db_session, n)

        def close(self):
            pass
    monkeypatch.setattr("app.voice.runner.SessionLocal", lambda: _Shared())
    monkeypatch.setattr(speech_service, "synthesize", lambda t: (tone(100), RATE))
    monkeypatch.setattr(speech_service, "transcribe", lambda p, r=None: "not at all")
    StressService.start_session(db_session, DEV)
    with client.websocket_connect(f"/ws/audio/{DEV}") as ws:
        ws.send_text(json.dumps({"type": "hello", "device_id": DEV, "sample_rate": RATE}))
        first = ws.receive_json()
        assert first["type"] == "speak_start" and first["audio"] is True
        got = 0
        while True:
            m = ws.receive()
            if m.get("bytes"):
                got += len(m["bytes"])
                continue
            d = json.loads(m["text"])
            if d["type"] == "speak_end":
                ws.send_text(json.dumps({"type": "speak_done"}))
            elif d["type"] == "listen":
                ws.send_bytes(tone(600) + silence(1200))
            elif d["type"] == "session_end":
                assert d["score"] is not None
                break
        assert got > 0


def test_tts_auto_falls_back_to_macos_say(monkeypatch):
    monkeypatch.setattr(settings, "TTS_PROVIDER", "auto")
    monkeypatch.setattr(speech_service, "_groq_tts_blocked_until", 0.0)
    calls = {"groq": 0, "say": 0}

    def fake_groq(t):
        calls["groq"] += 1
        return None

    def fake_say(t):
        calls["say"] += 1
        return tone(100), RATE
    monkeypatch.setattr(speech_service, "_synthesize_groq", fake_groq)
    monkeypatch.setattr(speech_service, "_synth_macos", fake_say)
    assert speech_service.synthesize("hello") is not None
    assert speech_service.synthesize("again") is not None   # Groq is skipped while blocked
    assert calls == {"groq": 1, "say": 2}
    monkeypatch.setattr(settings, "TTS_PROVIDER", "groq")
    assert speech_service.synthesize("x") is None            # explicit provider: no fallback

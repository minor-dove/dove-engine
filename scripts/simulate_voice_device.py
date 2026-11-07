"""
Simulated Dove device for the voice WebSocket (no hardware needed).

Connects to /ws/audio/{device_id}, plays the device side of the protocol (app/voice/runner.py):
answers every 'listen' with a spoken sentence (macOS `say`, else a tone), writes any TTS audio it
receives to ./sim_tts_N.wav. Start a session first:  POST /api/v1/stress/sessions {"device_id": "..."}

  python scripts/simulate_voice_device.py --device dove-sim --url ws://localhost:8000
"""

import argparse
import asyncio
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave

import websockets

RATE = 16000
ANSWERS = ["Honestly sometimes, work has been intense", "not at all", "a little bit I guess",
           "fairly often today", "I'd say sometimes"]


def speak_pcm(text: str) -> bytes:
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as d:
            a, w = os.path.join(d, "a.aiff"), os.path.join(d, "a.wav")
            subprocess.run(["say", "-o", a, text], check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", a, w], check=True)
            with wave.open(w, "rb") as f:
                return f.readframes(f.getnframes())
    n = RATE
    return struct.pack("<%dh" % n, *[int(8000 * math.sin(2 * math.pi * 300 * i / RATE)) for i in range(n)])


async def main(url: str, device: str) -> None:
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:5.1f}s] {m}", flush=True)
    answers = iter(ANSWERS)
    tts_n, tts_buf = 0, b""
    async with websockets.connect(f"{url}/ws/audio/{device}", max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": device, "sample_rate": RATE}))
        async for msg in ws:
            if isinstance(msg, bytes):
                tts_buf += msg
                continue
            d = json.loads(msg)
            t = d["type"]
            if t == "speak_start":
                tts_buf = b""
                log(f"speak_start audio={d['audio']} {d['duration_ms']} ms")
            elif t == "speak_end":
                if tts_buf:
                    tts_n += 1
                    with wave.open(f"sim_tts_{tts_n}.wav", "wb") as f:
                        f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE); f.writeframes(tts_buf)
                    log(f"  received {len(tts_buf)} bytes TTS -> sim_tts_{tts_n}.wav")
                await ws.send(json.dumps({"type": "speak_done"}))
            elif t == "listen":
                text = next(answers, "sometimes")
                log(f"listen -> answering: {text!r}")
                pcm = speak_pcm(text) + bytes(RATE * 2 * 2)  # + 2 s of silence so the VAD closes the utterance
                for i in range(0, len(pcm), 3200):            # 100 ms chunks
                    await ws.send(pcm[i:i + 3200])
                    await asyncio.sleep(0.02)
            elif t == "stop_listen":
                pass
            elif t in ("session_end", "error"):
                log(f"{t}: {d}")
                break


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000")
    ap.add_argument("--device", default="dove-sim")
    a = ap.parse_args()
    asyncio.run(main(a.url, a.device))

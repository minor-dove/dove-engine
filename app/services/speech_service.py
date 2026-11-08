"""Speech-to-text and text-to-speech via Groq. Both return None on failure (callers degrade gracefully)."""

import logging
import re
from typing import List, Optional, Tuple

import httpx

from app.core.config import settings
from app.services.llm_service import LLMService
from app.voice.audio import pcm_to_wav, resample, wav_to_pcm

logger = logging.getLogger(__name__)

GROQ = "https://api.groq.com/openai/v1"
TTS_MAX_CHARS = 190  # orpheus rejects long inputs


def transcribe(pcm: bytes, rate: int = None) -> Optional[str]:
    """PCM16 mono -> text (None if unconfigured/failed/empty)."""
    if not pcm or not LLMService.is_configured():
        return None
    rate = rate or settings.AUDIO_SAMPLE_RATE
    try:
        with httpx.Client(timeout=settings.GROQ_TIMEOUT_SECONDS) as c:
            r = c.post(
                f"{GROQ}/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                files={"file": ("utterance.wav", pcm_to_wav(pcm, rate), "audio/wav")},
                data={"model": settings.GROQ_STT_MODEL, "language": "en",
                      "response_format": "json", "temperature": "0"},
            )
        if r.status_code == 200:
            return (r.json().get("text") or "").strip() or None
        logger.warning(f"STT status {r.status_code}")
    except Exception as e:
        logger.error(f"STT failed: {type(e).__name__}")
    return None


def split_text(text: str, limit: int = TTS_MAX_CHARS) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: List[str] = []
    cur = ""
    for s in sentences:
        while len(s) > limit:  # hard split very long sentences on a space
            cut = s.rfind(" ", 0, limit) or limit
            cut = cut if cut > 0 else limit
            chunks.append(s[:cut])
            s = s[cut:].strip()
        if len(cur) + len(s) + 1 <= limit:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return chunks


def synthesize(text: str) -> Optional[Tuple[bytes, int]]:
    """Text -> (PCM16 mono at AUDIO_SAMPLE_RATE, rate). None if TTS is unavailable."""
    if not text.strip() or not LLMService.is_configured():
        return None
    out = b""
    try:
        with httpx.Client(timeout=settings.GROQ_TIMEOUT_SECONDS) as c:
            for part in split_text(text):
                r = c.post(
                    f"{GROQ}/audio/speech",
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json={"model": settings.GROQ_TTS_MODEL, "input": part,
                          "voice": settings.GROQ_TTS_VOICE, "response_format": "wav"},
                )
                if r.status_code != 200:
                    logger.warning(f"TTS status {r.status_code}: {r.text[:120]}")
                    return None
                pcm, rate = wav_to_pcm(r.content)
                out += resample(pcm, rate, settings.AUDIO_SAMPLE_RATE)
    except Exception as e:
        logger.error(f"TTS failed: {type(e).__name__}: {e}")
        return None
    return (out, settings.AUDIO_SAMPLE_RATE) if out else None

"""Energy-based end-of-utterance detector for 16-bit mono PCM (server-side endpointing)."""

from collections import deque
from typing import Deque, List

from app.core.config import settings
from app.voice.audio import rms

FRAME_MS = 20
START_FRAMES = 3      # consecutive loud frames that count as speech onset
PREROLL_FRAMES = 10   # keep this much audio before onset so the first syllable isn't clipped


class EnergyVAD:
    def __init__(self, rate: int = None, silence_ms: int = None, min_rms: int = None,
                 max_utterance_s: float = None):
        self.rate = rate or settings.AUDIO_SAMPLE_RATE
        self.frame_bytes = self.rate * FRAME_MS // 1000 * 2
        self.silence_frames = (silence_ms or settings.VOICE_SILENCE_MS) // FRAME_MS
        self.min_rms = min_rms or settings.VOICE_VAD_MIN_RMS
        self.max_frames = int((max_utterance_s or settings.VOICE_MAX_UTTERANCE_S) * 1000 / FRAME_MS)
        self._buf = b""
        self._noise = 0.0
        self._loud_run = 0
        self._silent_run = 0
        self._preroll: Deque[bytes] = deque(maxlen=PREROLL_FRAMES)
        self._frames: List[bytes] = []
        self.started = False
        self.done = False

    def _threshold(self) -> float:
        return max(float(self.min_rms), 2.5 * self._noise)

    def feed(self, chunk: bytes) -> bool:
        """Feed PCM bytes; returns True once a complete utterance has been captured."""
        if self.done:
            return True
        self._buf += chunk
        while len(self._buf) >= self.frame_bytes and not self.done:
            frame, self._buf = self._buf[: self.frame_bytes], self._buf[self.frame_bytes:]
            self._frame(frame)
        return self.done

    def _frame(self, frame: bytes) -> None:
        level = rms(frame)
        loud = level > self._threshold()
        if not loud:  # noise floor only learns from non-speech frames
            self._noise = level if self._noise == 0.0 else 0.95 * self._noise + 0.05 * level
        if not self.started:
            self._preroll.append(frame)
            self._loud_run = self._loud_run + 1 if loud else 0
            if self._loud_run >= START_FRAMES:
                self.started = True
                self._frames = list(self._preroll)
                self._silent_run = 0
            return
        self._frames.append(frame)
        self._silent_run = 0 if loud else self._silent_run + 1
        if self._silent_run >= self.silence_frames or len(self._frames) >= self.max_frames:
            self.done = True

    def audio(self) -> bytes:
        frames = self._frames
        # drop most of the trailing silence, keep ~200 ms
        trim = max(0, self._silent_run - 10)
        if trim:
            frames = frames[:-trim]
        return b"".join(frames)

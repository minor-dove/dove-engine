"""PCM16 helpers: WAV wrap/unwrap, linear resampling, RMS."""

import io
import math
import struct
import wave
from array import array
from typing import Tuple


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm(data: bytes) -> Tuple[bytes, int]:
    """Returns mono 16-bit PCM and its sample rate. Raises ValueError for unsupported WAVs."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("only 16-bit WAV supported")
        ch, rate, frames = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
    if ch == 1:
        return frames, rate
    a = array("h")
    a.frombytes(frames)
    mono = array("h", (sum(a[i:i + ch]) // ch for i in range(0, len(a) - ch + 1, ch)))
    return mono.tobytes(), rate


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    """Linear interpolation resampler (good enough for speech)."""
    if src == dst or not pcm:
        return pcm
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    n_out = int(len(a) * dst / src)
    out = array("h", bytes(2 * n_out))
    ratio = src / dst
    last = len(a) - 1
    for i in range(n_out):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        s0 = a[j]
        s1 = a[j + 1] if j < last else s0
        out[i] = int(s0 + (s1 - s0) * frac)
    return out.tobytes()


def rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack("<%dh" % n, pcm[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n)

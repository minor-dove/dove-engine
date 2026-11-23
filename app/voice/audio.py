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
    """Resample mono PCM16. Downsampling averages over each output sample's source window (a box low-pass,
    so no harsh aliasing); upsampling uses linear interpolation."""
    if src == dst or not pcm:
        return pcm
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    n_out = int(len(a) * dst / src)
    out = array("h", bytes(2 * n_out))
    ratio = src / dst
    last = len(a) - 1
    if src > dst:
        pre = [0]
        for v in a:
            pre.append(pre[-1] + v)

        def cum(x: float) -> float:  # integral of the sample stream up to fractional position x
            j = int(x)
            if j >= len(a):
                return float(pre[-1])
            return pre[j] + a[j] * (x - j)

        for i in range(n_out):
            lo, hi = i * ratio, (i + 1) * ratio
            out[i] = int((cum(hi) - cum(lo)) / (hi - lo))
        return out.tobytes()
    for i in range(n_out):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        s0 = a[j]
        s1 = a[j + 1] if j < last else s0
        out[i] = int(s0 + (s1 - s0) * frac)
    return out.tobytes()


def normalize_speech(pcm: bytes, target_rms: float = 4500.0, max_gain: float = 6.0,
                     ceiling: float = 30000.0) -> bytes:
    """Make synthesized speech loud and even on a small speaker: scale towards target_rms (capped gain) and
    soft-limit peaks with tanh so louder never means clipping."""
    if not pcm:
        return pcm
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    cur = math.sqrt(sum(x * x for x in a) / len(a))
    if cur < 1.0:
        return pcm
    g = min(max_gain, target_rms / cur)
    out = array("h", (int(ceiling * math.tanh(g * x / ceiling)) for x in a))
    return out.tobytes()


def shape_utterance(pcm: bytes, rate: int, fade_in_ms: int = 15, fade_out_ms: int = 90,
                    tail_ms: int = 250) -> bytes:
    """Make a synthesized utterance safe for a small class-D amp: fade in/out (no click at the edges) and end
    on real silence so the device never cuts the speaker off in the middle of a waveform (that is the
    'scratch' you hear at the end of a sentence)."""
    if not pcm:
        return pcm
    a = array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    n_in = min(len(a) // 2, rate * fade_in_ms // 1000)
    n_out = min(len(a) // 2, rate * fade_out_ms // 1000)
    for i in range(n_in):
        a[i] = int(a[i] * i / n_in)
    for i in range(n_out):
        a[len(a) - 1 - i] = int(a[len(a) - 1 - i] * i / n_out)
    return a.tobytes() + bytes(2 * (rate * tail_ms // 1000))


def rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack("<%dh" % n, pcm[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n)

"""Speech output quality (loud, even, no aliasing) and noise-transcript filtering."""

import math
from array import array

from app.services.speech_service import clean_transcript
from app.voice.audio import normalize_speech, resample, rms


def _sine(freq, rate, secs=0.5, amp=3000):
    n = int(rate * secs)
    return array("h", (int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(n))).tobytes()


def test_normalize_makes_quiet_speech_louder_and_never_clips():
    quiet = _sine(300, 16000, amp=1200)
    loud = normalize_speech(quiet)
    assert rms(loud) > 3 * rms(quiet)
    a = array("h"); a.frombytes(loud)
    assert max(map(abs, a)) <= 30000
    # already-loud audio is limited, not clipped
    hot = normalize_speech(_sine(300, 16000, amp=32000))
    b = array("h"); b.frombytes(hot)
    assert max(map(abs, b)) <= 30000


def test_normalize_gain_is_capped_and_silence_untouched():
    silence = array("h", [0] * 1000).tobytes()
    assert normalize_speech(silence) == silence
    near = array("h", [2] * 1000).tobytes()
    assert rms(normalize_speech(near)) <= 2 * 6.0 + 1  # max_gain 6x: noise floor is not blown up


def test_downsample_keeps_level_and_removes_alias():
    # 10 kHz tone at 24 kHz would alias to 6 kHz at 16 kHz with naive decimation; averaging attenuates it
    high = resample(_sine(10000, 24000), 24000, 16000)
    low = resample(_sine(500, 24000), 24000, 16000)
    assert rms(low) > 0.8 * rms(_sine(500, 16000))          # speech band keeps its level
    assert rms(high) < 0.6 * rms(low)                        # high band is attenuated
    assert abs(len(low) // 2 - 8000) <= 2


def test_noise_transcripts_are_not_answers():
    assert clean_transcript(".", 1.0) is None
    assert clean_transcript("...", 3.0) is None
    assert clean_transcript("you", 0.6) is None
    assert clean_transcript("Thank you.", 0.8) is None
    assert clean_transcript("you", 2.5) == "you"                  # a longer clip is a real (if odd) answer
    assert clean_transcript("not much, a bit stressed", 2.0) == "not much, a bit stressed"


def test_vad_keeps_quiet_sentence_tail_with_hysteresis():
    import random
    from app.voice.vad import EnergyVAD, FRAME_MS
    rate = 16000
    n = rate * FRAME_MS // 1000
    rnd = random.Random(1)

    def frame(level):  # noise-like frame with the requested RMS
        return array("h", (int(rnd.gauss(0, level)) for _ in range(n))).tobytes()

    vad = EnergyVAD(rate=rate, silence_ms=1000, min_rms=350)
    for _ in range(50):                 # 1 s of mic noise at 280 -> start threshold ~700
        vad.feed(frame(280))
    assert not vad.started
    for _ in range(25):                 # loud speech
        vad.feed(frame(1500))
    assert vad.started
    for _ in range(60):                 # quiet tail (~500): below the start level, above noise -> still speech
        vad.feed(frame(500))
    assert not vad.done
    for _ in range(60):                 # back to noise only -> utterance ends
        vad.feed(frame(280))
    assert vad.done


# ---- TTS provider selection / fallback ------------------------------------------------------------------

def _tts_env(monkeypatch, provider="auto", gemini=True, groq=True):
    from app.services import speech_service as sp
    monkeypatch.setattr(sp.settings, "TTS_PROVIDER", provider)
    monkeypatch.setattr(sp.settings, "GEMINI_API_KEY", "k" if gemini else None)
    monkeypatch.setattr(sp.settings, "GROQ_API_KEY", "gsk_real" if groq else None)
    return sp


def test_tts_order(monkeypatch):
    sp = _tts_env(monkeypatch)
    assert sp.tts_order() == ["gemini", "groq"]
    sp = _tts_env(monkeypatch, provider="groq")
    assert sp.tts_order() == ["groq"]                      # explicit provider: only that one
    sp = _tts_env(monkeypatch, gemini=False)
    assert sp.tts_order() == ["groq"]
    sp = _tts_env(monkeypatch, gemini=False, groq=False)
    assert sp.tts_order() == [] and sp.synthesize("hello") is None


def test_tts_falls_back_when_first_provider_fails(monkeypatch):
    sp = _tts_env(monkeypatch)
    monkeypatch.setattr(sp, "_synthesize_gemini", lambda t: None)          # e.g. 429
    tone = _sine(300, 16000, amp=1000)
    monkeypatch.setattr(sp, "_synthesize_groq", lambda t: tone)
    pcm, rate = sp.synthesize("hello")
    assert rate == 16000 and len(pcm) == len(tone) and rms(pcm) > rms(tone)   # normalised


def test_gemini_tts_parses_inline_audio(monkeypatch):
    import base64
    import httpx
    sp = _tts_env(monkeypatch)
    raw24 = _sine(400, 24000, secs=0.5)
    body = {"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(raw24).decode()}}]}}]}
    seen = {}

    def handler(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("x-goog-api-key")
        return httpx.Response(200, json=body)

    real = httpx.Client
    monkeypatch.setattr(sp.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    out = sp._synthesize_gemini("hello there")
    assert seen["key"] == "k" and "flash-lite-tts:generateContent" in seen["url"]
    assert abs(len(out) // 2 - 8000) <= 2                       # 24 kHz -> 16 kHz


def test_explicit_provider_means_only_that_provider(monkeypatch):
    sp = _tts_env(monkeypatch, provider="gemini")          # both keys present, owner chose gemini: never call groq
    assert sp.tts_order() == ["gemini"]
    monkeypatch.setattr(sp.settings, "STT_PROVIDER", "gemini")
    assert sp._order(sp.settings.STT_PROVIDER) == ["gemini"]
    monkeypatch.setattr(sp, "_synthesize_gemini", lambda t: None)
    monkeypatch.setattr(sp, "_synthesize_groq", lambda t: (_ for _ in ()).throw(AssertionError("groq called")))
    assert sp.synthesize("hello") is None


def test_gemini_stt_silence_marker_and_text(monkeypatch):
    import httpx
    sp = _tts_env(monkeypatch)
    monkeypatch.setattr(sp.settings, "STT_PROVIDER", "gemini")
    replies = iter(["[silence]", "I felt okay this morning"])

    def handler(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": next(replies)}]}}]})

    real = httpx.Client
    monkeypatch.setattr(sp.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    pcm = _sine(300, 16000, secs=2.0)
    assert sp.transcribe(pcm, 16000) is None
    assert sp.transcribe(pcm, 16000) == "I felt okay this morning"


def test_thinking_config_per_model_family():
    from app.services.llm_service import thinking_config
    assert thinking_config("gemini-2.5-flash") == {"thinkingBudget": 0}
    assert thinking_config("gemini-3.5-flash-lite") == {"thinkingLevel": "minimal"}

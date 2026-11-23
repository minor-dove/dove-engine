"""Adaptive check-ins: time-specific wording, profile-driven phrasing, follow-ups, learning after sessions."""

import json
from datetime import datetime, timezone

import pytest

from app.models.mood import MoodEvent
from app.models.stress import StressItemResponse, StressSession
from app.services import stress_service
from app.services.conversation_context import build_context, daypart_for
from app.services.profile_service import ProfileService
from app.services.stress_items import ITEM_STEMS, item_question, plan_items
from app.services.stress_service import StressService

DEV = "dove-esp32-01"


class FakeLLM:
    """Routes by system prompt; records every call so tests can assert on what the model was told."""

    def __init__(self, value=2):
        self.value = value
        self.calls = []   # (kind, system, user)
        self.profile_out = {
            "facts": ["works on a thesis"], "stressors": ["supervisor meeting on Friday"],
            "helps": ["short walks"], "interests": ["cycling"], "routine": [],
            "open_threads": [{"topic": "supervisor meeting on Friday", "hint": "ask how it went"}],
            "tone": "casual, short", "summary": "Talked about thesis pressure and the Friday meeting."}

    def __call__(self, system, user, max_tokens=200, temperature=0.0):
        if system.startswith("You rate"):
            kind, out = "score", {"value": self.value, "confidence": 0.9, "evidence": "quote"}
        elif system.startswith("You are Dove"):
            kind, out = "say", {"reply": "Sounds like a lot. So tell me about it in your own words?"}
        else:
            kind, out = "profile", self.profile_out
        self.calls.append((kind, system, user))
        return out

    def of(self, kind):
        return [c for c in self.calls if c[0] == kind]


@pytest.fixture(autouse=True)
def utc_user(db_session):
    from app.models.preference import UserPreference
    db_session.query(UserPreference).filter(UserPreference.id == 1).first().timezone = "UTC"
    db_session.commit()


@pytest.fixture
def llm(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(stress_service.llm_service, "generate_json", f)
    from app.services import profile_service
    monkeypatch.setattr(profile_service.llm_service, "generate_json", f)
    return f


def _at(h, m=0):
    return datetime(2026, 11, 23, h, m, tzinfo=timezone.utc)   # default test timezone is UTC


def _complete(db, mock, now, answers):
    res = StressService.start_session(db, DEV, mqtt_publisher=mock, now=now)
    for a in answers:
        res = StressService.submit_answer(db, res["session_id"], a, mqtt_publisher=mock)
    return res


# ---- 1. questions are specific to WHEN they are asked ----------------------------------------------

def test_daypart_and_window(db_session):
    assert [daypart_for(h) for h in (7, 13, 18, 23)] == ["morning", "afternoon", "evening", "night"]
    assert build_context(db_session, DEV, _at(9))["window"] == "so far this morning"
    assert build_context(db_session, DEV, _at(15))["window"] == "so far today"


def test_second_session_asks_about_since_last_time(db_session, mock_mqtt, llm):
    _complete(db_session, mock_mqtt, _at(9), ["short"] * 5)
    res = StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(14))
    s = db_session.get(StressSession, res["session_id"])
    assert s.window == "since we last talked" and s.daypart == "afternoon"
    prompt = llm.of("say")[-1][2]
    assert "since we last talked" in prompt and "check-in number 2 today" in prompt
    assert "Monday" in prompt and "14:00" in prompt


def test_offline_opener_is_time_aware_not_today(db_session, mock_mqtt, monkeypatch):
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)
    res = StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(9))
    assert res["question"].startswith("Good morning!") and "so far this morning" in res["question"].lower()
    assert "Today," not in res["question"]


def test_earlier_session_topics_are_in_the_prompt(db_session, mock_mqtt, llm):
    _complete(db_session, mock_mqtt, _at(9), ["short"] * 5)
    StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(14))
    assert "Earlier today you already talked about" in llm.of("say")[-1][2]


def test_plan_prefers_items_for_the_daypart_and_does_not_repeat_today():
    morning = plan_items({}, daypart="morning")
    evening = plan_items({}, daypart="evening")
    assert morning != evening
    again = plan_items({i: 1 for i in morning}, daypart="morning", asked_today={i: 1 for i in morning})
    assert not set(again[:3]) & set(morning[:3])


def test_item_question_wording():
    assert item_question(3, "since we last talked").startswith("Since we last talked, how often")
    assert set(ITEM_STEMS) == set(range(1, 11))


# ---- 2 + 3. not generic, a conversation ---------------------------------------------------------------

def test_profile_is_learned_after_a_session_and_used_next_time(db_session, mock_mqtt, llm):
    _complete(db_session, mock_mqtt, _at(9), ["very often, thesis stress"] * 5)
    prof = ProfileService.get(db_session, DEV)
    assert prof["facts"] == ["works on a thesis"]
    assert prof["open_threads"][0]["topic"] == "supervisor meeting on Friday"
    assert ProfileService.sessions_count(db_session, DEV) == 1
    first = db_session.query(StressSession).first()
    assert first.summary.startswith("Talked about thesis")

    StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(15))
    prompt = llm.of("say")[-1][2]
    assert "works on a thesis" in prompt and "supervisor meeting on Friday" in prompt


def test_followup_makes_it_a_conversation_and_is_not_scored(db_session, mock_mqtt, llm):
    long_answer = "honestly it has been a lot today with the deadline and a couple of meetings back to back"
    res = StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(9))
    sid = res["session_id"]
    res = StressService.submit_answer(db_session, sid, "not much", mqtt_publisher=mock_mqtt)   # 1st item, terse
    assert db_session.get(StressSession, sid).awaiting_followup is False
    res = StressService.submit_answer(db_session, sid, long_answer, mqtt_publisher=mock_mqtt)
    s = db_session.get(StressSession, sid)
    assert s.awaiting_followup is False   # follow-ups only after answers 1 and 3 (index 1 = after the 1st)
    # first answer was < 8 words so no follow-up; third answer is long enough
    res = StressService.submit_answer(db_session, sid, long_answer, mqtt_publisher=mock_mqtt)
    s = db_session.get(StressSession, sid)
    assert s.awaiting_followup is True and s.followups_used == 1
    answered_before = len(s.responses)
    res = StressService.submit_answer(db_session, sid, "mostly the deadline, I keep rewriting it", mqtt_publisher=mock_mqtt)
    s = db_session.get(StressSession, sid)
    assert len(s.responses) == answered_before            # the chat reply is NOT a scored answer
    assert s.awaiting_followup is False and s.current_index == answered_before


def test_followups_respect_budget_and_can_be_disabled(db_session, mock_mqtt, llm, monkeypatch):
    monkeypatch.setattr(stress_service.settings, "STRESS_MAX_FOLLOWUPS", 0)
    long_answer = "honestly it has been a lot today with the deadline and a couple of meetings back to back"
    res = _complete(db_session, mock_mqtt, _at(9), [long_answer] * 5)
    s = db_session.query(StressSession).first()
    assert s.followups_used == 0 and res["status"] == "completed"


def test_terse_talkers_are_not_pushed_into_follow_ups(db_session, mock_mqtt, llm):
    prof = ProfileService.get(db_session, DEV)
    prof["avg_answer_words"] = 2.0
    ProfileService.save(db_session, DEV, prof)
    long_answer = "honestly it has been a lot today with the deadline and a couple of meetings back to back"
    _complete(db_session, mock_mqtt, _at(9), [long_answer] * 5)
    assert db_session.query(StressSession).first().followups_used == 0


def test_scoring_never_sees_profile_or_emotion(db_session, mock_mqtt, llm):
    db_session.add(MoodEvent(event_id="e1", device_id=DEV, mood_id=1, emotion="ANGRY", is_valid=True,
                             recorded_at=datetime.now(timezone.utc)))
    db_session.commit()
    _complete(db_session, mock_mqtt, _at(9), ["sometimes"] * 5)
    for _, system, user in llm.of("score"):
        assert "expression" not in user.lower() and "angry" not in user.lower()
        assert "thesis" not in user.lower()


def test_score_unchanged_by_conversation_features(db_session, mock_mqtt, llm):
    # identical scored answers -> identical score, whatever the profile / phrasing / follow-ups were
    a = _complete(db_session, mock_mqtt, _at(9), ["sometimes"] * 5)
    prof = ProfileService.get(db_session, DEV)
    prof["stressors"] = ["everything"]
    ProfileService.save(db_session, DEV, prof)
    b = _complete(db_session, mock_mqtt, _at(15), ["sometimes"] * 5)
    assert a["score"] == b["score"]


# ---- 4. optimized after every session --------------------------------------------------------------------

def test_items_with_unusable_answers_are_deprioritised_next_time(db_session, mock_mqtt, monkeypatch):
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)
    prof = ProfileService.get(db_session, DEV)
    prof["item_stats"] = {"3": {"asked": 4, "dropped": 4}}
    ProfileService.save(db_session, DEV, prof)
    rates = ProfileService.drop_rates(ProfileService.get(db_session, DEV))
    assert rates[3] == 1.0
    assert 3 not in plan_items({}, daypart="afternoon", drop_rates=rates)


def test_stats_updated_even_when_llm_is_offline(db_session, mock_mqtt, monkeypatch):
    monkeypatch.setattr(stress_service.llm_service, "generate_json", lambda *a, **k: None)
    _complete(db_session, mock_mqtt, _at(9), ["sometimes"] * 5)
    prof = ProfileService.get(db_session, DEV)
    assert sum(v["asked"] for v in prof["item_stats"].values()) == 5
    assert prof["avg_answer_words"] == 1.0
    assert prof["recent_sessions"][-1]["summary"] == "morning check-in"


def test_profile_sanitised(db_session, mock_mqtt, llm):
    llm.profile_out = {"facts": ["x" * 500, "  a   b ", 5, None], "open_threads": "nope", "tone": 7,
                       "summary": "ok"}
    _complete(db_session, mock_mqtt, _at(9), ["sometimes"] * 5)
    prof = ProfileService.get(db_session, DEV)
    assert len(prof["facts"][0]) == 100 and prof["facts"][1] == "a b" and len(prof["facts"]) == 2


# ---- transparency / control -------------------------------------------------------------------------------

def test_profile_api_view_and_delete(client, db_session, mock_mqtt, llm):
    _complete(db_session, mock_mqtt, _at(9), ["sometimes"] * 5)
    r = client.get("/api/v1/stress/profile").json()
    assert r["sessions_learned_from"] == 1 and r["profile"]["facts"] == ["works on a thesis"]
    assert client.delete("/api/v1/stress/profile").json()["deleted"] is True
    assert client.get("/api/v1/stress/profile").json()["profile"]["facts"] == []


def test_old_database_gets_new_columns(monkeypatch):
    """A DB created before this feature must be upgraded in place by init_db (create_all won't alter tables)."""
    from sqlalchemy import create_engine, inspect, text
    from app.core import init_db as init_mod
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE stress_sessions (id VARCHAR(36) PRIMARY KEY, status VARCHAR(16))"))
        c.execute(text("INSERT INTO stress_sessions VALUES ('a', 'completed')"))
    monkeypatch.setattr(init_mod, "engine", eng)
    init_mod._ensure_columns()
    init_mod._ensure_columns()   # idempotent
    cols = {c["name"] for c in inspect(eng).get_columns("stress_sessions")}
    assert {"daypart", "window", "followups_used", "awaiting_followup", "summary"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT followups_used FROM stress_sessions")).scalar() == 0


def test_repeat_request_repeats_the_question_and_changes_nothing(db_session, mock_mqtt, llm):
    from app.services.stress_service import is_repeat_request
    for t in ("What did you say? Can you speak again?", "sorry?", "huh", "can you repeat that", "speak louder"):
        assert is_repeat_request(t)
    for t in ("not much", "quite a bit stressed about the deadline", "sometimes"):
        assert not is_repeat_request(t)
    res = StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(9))
    opener = res["question"]
    r2 = StressService.submit_answer(db_session, res["session_id"], "What did you say? Can you speak again?",
                                     mqtt_publisher=mock_mqtt)
    s = db_session.get(StressSession, res["session_id"])
    from app.services.stress_service import last_question
    assert last_question("Good to hear. You seem calmer. How often did you feel on top of things?") == \
        "How often did you feel on top of things?"
    assert last_question("That's all for now.") == "That's all for now."
    assert r2["question"] == "Sure. " + last_question(opener)
    assert s.current_index == 0 and s.clarify_used is False and len(s.responses) == 0
    r3 = StressService.submit_answer(db_session, res["session_id"], "can you repeat that", mqtt_publisher=mock_mqtt)
    assert r3["question"] == "Sure. " + last_question(opener)          # no 'Sure. Sure.'


# ---- Gemini provider --------------------------------------------------------------------------------------

def _mock_gemini(monkeypatch, handler):
    import httpx
    from app.services import llm_service as L
    real = httpx.Client
    monkeypatch.setattr(L.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(L.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(L.settings, "LLM_PROVIDER", "auto")


def test_provider_selection(monkeypatch):
    from app.services import llm_service as L
    monkeypatch.setattr(L.settings, "GROQ_API_KEY", "gsk_real")
    monkeypatch.setattr(L.settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(L.settings, "LLM_PROVIDER", "auto")
    assert L.provider() == "groq"
    monkeypatch.setattr(L.settings, "GEMINI_API_KEY", "k")
    assert L.provider() == "gemini"                       # gemini wins in auto when its key exists
    monkeypatch.setattr(L.settings, "LLM_PROVIDER", "groq")
    assert L.provider() == "groq"
    monkeypatch.setattr(L.settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(L.settings, "GEMINI_API_KEY", None)
    assert L.provider() is None and not L.LLMService.is_configured()


def test_gemini_json_call_shape_and_parse(monkeypatch):
    import json as _json
    import httpx
    from app.services import llm_service as L
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), _json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"reply": "hi there"}'}]}}]})

    _mock_gemini(monkeypatch, handler)
    out = L.generate_json("sys prompt", "user prompt", max_tokens=123, temperature=0.7)
    assert out == {"reply": "hi there"}
    assert seen["key"] == "test-key" and ":generateContent" in seen["url"] and "key=" not in seen["url"]
    b = seen["body"]
    assert b["systemInstruction"]["parts"][0]["text"] == "sys prompt"
    assert b["contents"][0]["parts"][0]["text"] == "user prompt"
    g = b["generationConfig"]
    assert g["responseMimeType"] == "application/json" and g["maxOutputTokens"] == 123 and g["temperature"] == 0.7
    assert g["thinkingConfig"] == {"thinkingLevel": "minimal"}


def test_gemini_failure_returns_none_and_chat_falls_back(monkeypatch):
    import httpx
    from app.services import llm_service as L
    _mock_gemini(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    assert L.generate_json("s", "u") is None
    assert L.LLMService.generate_response([{"role": "user", "content": "hi"}]) == L.FALLBACK_REPLY
    _mock_gemini(monkeypatch, lambda req: httpx.Response(200, json={"candidates": []}))   # blocked / empty
    assert L.generate_json("s", "u") is None


def test_gemini_chat_maps_roles(monkeypatch):
    import json as _json
    import httpx
    from app.services import llm_service as L
    seen = {}

    def handler(req):
        seen["body"] = _json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hello!"}]}}]})

    _mock_gemini(monkeypatch, handler)
    out = L.LLMService.generate_response([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert out == "hello!"
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model"]

def test_skip_request_drops_the_item_and_moves_on(db_session, mock_mqtt, llm):
    from app.services.stress_service import is_skip_request
    assert is_skip_request("I'm going to go to the next one.") and is_skip_request("skip this")
    assert not is_skip_request("not much") and not is_skip_request("it was a nice start")
    res = StressService.start_session(db_session, DEV, mqtt_publisher=mock_mqtt, now=_at(9))
    r = StressService.submit_answer(db_session, res["session_id"], "I'm going to go to the next one.",
                                    mqtt_publisher=mock_mqtt)
    s = db_session.get(StressSession, res["session_id"])
    assert s.current_index == 1 and s.clarify_used is False
    assert s.responses[0].value is None and s.responses[0].evidence == "skipped by user"
    assert not llm.of("score")            # nothing was scored


def test_spoken_lines_are_kept_short():
    long = ("That sounds like a really heavy morning with so much going on at once and I can hear how much it is. "
            "It makes sense that you feel stretched when the days start like this and the list never ends. "
            "So, how often did you feel on top of things so far this morning?")
    out = StressService._shorten(long)
    assert len(out) <= 230 and out.endswith("on top of things so far this morning?")
    assert StressService._shorten("Short one. Fine?") == "Short one. Fine?"

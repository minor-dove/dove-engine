"""
LLM Service: Groq API Integration.
Handles conversational response generation with timeout handling and offline fallback.
Keeps API keys secure and never logs sensitive prompts or credentials.
"""

import logging
from typing import List, Dict, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Default system persona for DOVE
DEFAULT_SYSTEM_PROMPT = """You are DOVE, an empathetic, caring, and intuitive AI desk pet.
You sit quietly on the user's desk, keeping them company.
Your personality is gentle, warm, observant, and non-judgmental.
You speak in short, natural sentences (typically 1 to 3 sentences).
You never claim to know for certain how the user feels; you treat mood signals as gentle hints.
You never assume personal facts that the user hasn't explicitly shared.
You help with encouragement, reflections, and reminders when relevant.
"""

FALLBACK_REPLY = "I'm right here with you. I'm having a little trouble connecting to my cloud mind right now, but I'm listening."


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def groq_configured() -> bool:
    """True if a real Groq API key is present (needed for voice STT/TTS and the groq text provider)."""
    return bool(
        settings.GROQ_API_KEY
        and settings.GROQ_API_KEY.strip()
        and not settings.GROQ_API_KEY.startswith("gsk_placeholder")
    )


def gemini_configured() -> bool:
    return bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())


def provider() -> Optional[str]:
    """Which backend answers text prompts: 'gemini', 'groq' or None (offline fallbacks)."""
    want = (settings.LLM_PROVIDER or "auto").lower()
    if want == "gemini":
        return "gemini" if gemini_configured() else None
    if want == "groq":
        return "groq" if groq_configured() else None
    if gemini_configured():
        return "gemini"
    return "groq" if groq_configured() else None


def thinking_config(model: str) -> Dict:
    """Disable/minimise hidden reasoning for speed. 2.5 models take a token budget; 3.x models a level
    (and reject thinkingBudget=0)."""
    return {"thinkingBudget": 0} if model.startswith("gemini-2.5") else {"thinkingLevel": "minimal"}


def _gemini_call(system_prompt: str, contents: List[Dict], temperature: float, max_tokens: int,
                 json_mode: bool) -> Optional[str]:
    """One Gemini generateContent call -> text, or None on any failure. Retries once on 429."""
    gen = {"temperature": temperature, "maxOutputTokens": max_tokens,
           # these check-in prompts need speed, not deliberation: minimal hidden 'thinking'
           "thinkingConfig": thinking_config(settings.GEMINI_MODEL)}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    payload = {"systemInstruction": {"parts": [{"text": system_prompt}]}, "contents": contents,
               "generationConfig": gen}
    headers = {"x-goog-api-key": settings.GEMINI_API_KEY, "Content-Type": "application/json"}
    url = GEMINI_URL.format(model=settings.GEMINI_MODEL)
    try:
        with httpx.Client(timeout=settings.GROQ_TIMEOUT_SECONDS) as client:
            r = client.post(url, json=payload, headers=headers)
            if r.status_code == 429:
                import time
                logger.warning("Gemini rate-limited; retrying in 3s")
                time.sleep(3.0)
                r = client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                cands = r.json().get("candidates") or []
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    text = "".join(p.get("text", "") for p in parts).strip()
                    if text:
                        return text
                logger.warning("Gemini returned no text (blocked or empty)")
                return None
            logger.warning(f"Gemini status {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"Gemini call failed: {type(e).__name__}")
    return None


class LLMService:
    """
    Text LLM client (Gemini or Groq, see settings.LLM_PROVIDER).
    Provides graceful fallback when offline or unconfigured.
    """

    @staticmethod
    def is_configured() -> bool:
        """True if a text LLM provider is usable."""
        return provider() is not None

    @staticmethod
    def generate_response(
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Generates conversational response using Groq API.
        Falls back gracefully if the service is unreachable or unconfigured.
        """
        if not LLMService.is_configured():
            logger.info("No LLM provider configured. Using local friendly fallback response.")
            return "Hey there! I'm here at your desk with you. How's everything going?"

        prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        if provider() == "gemini":
            contents = [{"role": "model" if m.get("role") == "assistant" else "user",
                         "parts": [{"text": m.get("content", "")}]} for m in messages if m.get("content")]
            text = _gemini_call(prompt, contents, settings.GROQ_TEMPERATURE, settings.GROQ_MAX_TOKENS, False)
            return text or FALLBACK_REPLY
        payload = {
            "model": settings.GROQ_MODEL,
            "messages": [{"role": "system", "content": prompt}] + messages,
            "temperature": settings.GROQ_TEMPERATURE,
            "max_tokens": settings.GROQ_MAX_TOKENS,
        }

        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }

        try:
            with httpx.Client(timeout=settings.GROQ_TIMEOUT_SECONDS) as client:
                response = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers=headers
                )
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        content = msg.get("content") or msg.get("reasoning_content") or ""
                        content = content.strip()
                        if content:
                            return content
                        logger.warning("Groq API returned an empty message content; using fallback reply.")
                logger.warning(f"Groq API returned status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error calling Groq API: {type(e).__name__}: {str(e)}")

        return FALLBACK_REPLY


def _extract_json(text: str):
    """Parse a JSON object out of an LLM reply (tolerates code fences / prose)."""
    import json
    import re
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def generate_json(system_prompt: str, user_prompt: str, max_tokens: int = 200, temperature: float = 0.0):
    """
    One-shot call returning a parsed JSON object, or None when unconfigured/failed.
    Callers must supply their own deterministic fallback.
    """
    prov = provider()
    if prov is None:
        return None
    if prov == "gemini":
        text = _gemini_call(system_prompt, [{"role": "user", "parts": [{"text": user_prompt}]}],
                            temperature, max_tokens, True)
        return _extract_json(text or "")
    if not groq_configured():
        return None
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=settings.GROQ_TIMEOUT_SECONDS) as client:
            r = client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
            if r.status_code == 429:  # rate limited: wait briefly (<= 4 s, the spoken turn must not stall) and retry once
                import time
                try:
                    wait = min(float(r.headers.get("retry-after", "2")), 4.0)
                except ValueError:
                    wait = 2.0
                logger.warning(f"Groq JSON call rate-limited; retrying in {wait:.1f}s")
                time.sleep(wait)
                r = client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
            if r.status_code == 200:
                choices = r.json().get("choices", [])
                if choices:
                    return _extract_json(choices[0].get("message", {}).get("content") or "")
            logger.warning(f"Groq JSON call status {r.status_code}")
    except Exception as e:
        logger.error(f"Groq JSON call failed: {type(e).__name__}")
    return None

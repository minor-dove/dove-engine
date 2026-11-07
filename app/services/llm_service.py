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


class LLMService:
    """
    Communicates with Groq LLM API.
    Provides graceful fallback when offline or unconfigured.
    """

    @staticmethod
    def is_configured() -> bool:
        """Returns True if a real Groq API key is present."""
        return bool(
            settings.GROQ_API_KEY
            and settings.GROQ_API_KEY.strip()
            and not settings.GROQ_API_KEY.startswith("gsk_placeholder")
        )

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
            logger.info("Groq API key not configured. Using local friendly fallback response.")
            return "Hey there! I'm here at your desk with you. How's everything going?"

        prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
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


def generate_json(system_prompt: str, user_prompt: str):
    """
    One-shot Groq call returning a parsed JSON object, or None when unconfigured/failed.
    Callers must supply their own deterministic fallback.
    """
    if not LLMService.is_configured():
        return None
    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=settings.GROQ_TIMEOUT_SECONDS) as client:
            r = client.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers)
            if r.status_code == 200:
                choices = r.json().get("choices", [])
                if choices:
                    return _extract_json(choices[0].get("message", {}).get("content") or "")
            logger.warning(f"Groq JSON call status {r.status_code}")
    except Exception as e:
        logger.error(f"Groq JSON call failed: {type(e).__name__}")
    return None

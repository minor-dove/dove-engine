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

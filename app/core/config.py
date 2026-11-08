"""
Application Configuration Module.
Loads environment variables and provides typed settings with Pydantic.
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for DOVE backend."""

    # Application settings
    APP_NAME: str = "DOVE Backend"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Database settings (PostgreSQL with pgvector or SQLite for local dev/testing)
    DATABASE_URL: str = "sqlite:///./dove_dev.db"

    # MQTT Broker settings (Mosquitto)
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_KEEPALIVE: int = 60
    MQTT_CLIENT_ID: str = "dove-backend-worker"
    MQTT_RECONNECT_DELAY_SECONDS: int = 5

    # Groq LLM API settings
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_TEMPERATURE: float = 0.7
    GROQ_MAX_TOKENS: int = 300
    GROQ_TIMEOUT_SECONDS: float = 25.0

    # Voice (WebSocket audio): 16-bit mono PCM both directions at AUDIO_SAMPLE_RATE
    AUDIO_SAMPLE_RATE: int = 16000
    GROQ_STT_MODEL: str = "whisper-large-v3-turbo"
    GROQ_TTS_MODEL: str = "canopylabs/orpheus-v1-english"
    GROQ_TTS_VOICE: str = "autumn"
    TTS_PROVIDER: str = "auto"                 # auto = Groq, falling back to macOS `say` on a Mac dev server | groq | macos_say
    VOICE_SEND_PACE: float = 2.0               # TTS streamed at N x realtime (0 = as fast as possible)
    VOICE_FALLBACK_SPEED: float = 1.0          # text-only mouth timing speed-up (tests use a large value)
    VOICE_SILENCE_MS: int = 1000               # end of utterance after this much silence
    VOICE_NO_SPEECH_TIMEOUT_S: float = 10.0
    VOICE_MAX_UTTERANCE_S: float = 20.0
    VOICE_VAD_MIN_RMS: int = 350               # int16 RMS floor for 'speech'
    VOICE_MAX_MISSES: int = 2                  # silent answers before the session is abandoned

    # Long-term Memory & RAG settings
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_DIMENSION: int = 384

    # Proactive Interaction Engine settings
    PROACTIVE_COOLDOWN_MINUTES: int = 30
    PROACTIVE_ENABLED_DEFAULT: bool = True
    QUIET_HOURS_START_DEFAULT: str = "22:00"
    QUIET_HOURS_END_DEFAULT: str = "07:00"
    USER_TIMEZONE_DEFAULT: str = "Asia/Kolkata"

    # Stress session planner (presence-based, min STRESS_DAILY_TARGET sessions/day)
    STRESS_DAILY_TARGET: int = 3
    STRESS_DAY_START: str = "09:00"            # local; first session slot opens here
    STRESS_DAY_END: str = "21:00"              # local; no sessions started after this
    STRESS_MIN_GAP_MINUTES: int = 120          # gap between completed sessions
    STRESS_CATCHUP_GAP_MINUTES: int = 20       # used when the day is running out of time
    STRESS_RETRY_MINUTES: int = 15             # wait after an unfinished attempt
    STRESS_PRESENCE_SETTLE_SECONDS: int = 60   # user must be present this long first
    STRESS_SESSION_TIMEOUT_MINUTES: int = 10   # idle active session is closed

    # Mood ingestion settings
    MOOD_MAX_EVENT_GAP_SECONDS: int = 150  # 2.5 minutes between events (device posts every 60s)
    MOOD_EVENT_MAX_AGE_SECONDS: int = 1800  # 30 minutes stale threshold

    # Scheduler settings
    SCHEDULER_CHECK_INTERVAL_SECONDS: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached instance of application settings."""
    return Settings()


settings = get_settings()

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

    # Long-term Memory & RAG settings
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_DIMENSION: int = 384

    # Proactive Interaction Engine settings
    PROACTIVE_COOLDOWN_MINUTES: int = 30
    PROACTIVE_ENABLED_DEFAULT: bool = True
    QUIET_HOURS_START_DEFAULT: str = "22:00"
    QUIET_HOURS_END_DEFAULT: str = "07:00"
    USER_TIMEZONE_DEFAULT: str = "Asia/Kolkata"

    # Mood Trigger Engine settings
    MOOD_CONSECUTIVE_REQUIRED: int = 10
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

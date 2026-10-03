"""
User preferences model: Proactive settings, quiet hours, timezones, and routine schedules.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.core.database import Base
from app.core.config import settings


class UserPreference(Base):
    """
    Stores authoritative user configuration for DOVE interactions.
    """
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, default=1)
    quiet_hours_start = Column(String(8), nullable=False, default=settings.QUIET_HOURS_START_DEFAULT)  # e.g., "22:00"
    quiet_hours_end = Column(String(8), nullable=False, default=settings.QUIET_HOURS_END_DEFAULT)      # e.g., "07:00"
    proactive_enabled = Column(Boolean, nullable=False, default=settings.PROACTIVE_ENABLED_DEFAULT)
    cooldown_minutes = Column(Integer, nullable=False, default=settings.PROACTIVE_COOLDOWN_MINUTES)
    timezone = Column(String(64), nullable=False, default=settings.USER_TIMEZONE_DEFAULT)
    morning_time = Column(String(8), nullable=False, default="08:00")
    midday_time = Column(String(8), nullable=False, default="13:00")
    evening_time = Column(String(8), nullable=False, default="19:00")
    night_time = Column(String(8), nullable=False, default="22:30")
    night_enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            f"<UserPreference(quiet={self.quiet_hours_start}-{self.quiet_hours_end}, "
            f"proactive={self.proactive_enabled}, cooldown={self.cooldown_minutes}m)>"
        )

"""
User profile built from what the person says in check-in conversations (speech content only;
never from camera data). Stored locally, viewable and deletable via /api/v1/stress/profile.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from app.core.database import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    data = Column(Text, nullable=False, default="{}")        # JSON, see profile_service.EMPTY_PROFILE
    sessions_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

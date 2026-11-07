"""
Device model: Tracks physical ESP32 desk pet hardware.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from app.core.database import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False, default="DOVE Desk Pet")
    status = Column(String(32), nullable=False, default="offline")  # online, offline, degraded
    firmware_version = Column(String(32), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<Device(id='{self.id}', name='{self.name}', status='{self.status}')>"

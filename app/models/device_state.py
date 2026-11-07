"""Live device state reported over MQTT: user presence and privacy (do-not-disturb) mode."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from app.core.database import Base


class DeviceState(Base):
    __tablename__ = "device_states"

    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    present = Column(Boolean, nullable=False, default=False)
    present_since = Column(DateTime(timezone=True), nullable=True)
    last_present_at = Column(DateTime(timezone=True), nullable=True)
    privacy_on = Column(Boolean, nullable=False, default=False)
    privacy_since = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

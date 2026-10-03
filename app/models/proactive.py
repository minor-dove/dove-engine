"""
Proactive interaction tracking and cooldown models.
Enforces 30-minute cooldown and audit trail for all proactive decisions.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from app.core.database import Base


class ProactiveCooldown(Base):
    """
    Maintains the proactive interaction cooldown lock per device.
    User-initiated conversations bypass this, but mood/routine checks must honor it.
    """
    __tablename__ = "proactive_cooldowns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    last_proactive_at = Column(DateTime(timezone=True), nullable=True)
    cooldown_until = Column(DateTime(timezone=True), nullable=True, index=True)
    last_trigger_type = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<ProactiveCooldown(device='{self.device_id}', until='{self.cooldown_until}')>"


class ProactiveTriggerLog(Base):
    """
    Audit log of proactive check-in triggers and their outcomes.
    Status: accepted, skipped, generated, delivered, failed.
    """
    __tablename__ = "proactive_trigger_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    trigger_type = Column(String(64), nullable=False)  # mood_angry, mood_sad, routine_morning, etc.
    status = Column(String(32), nullable=False)        # accepted, skipped, generated, delivered, failed
    reason = Column(String(256), nullable=True)       # cooldown_active, quiet_hours, active_session, etc.
    starter_id = Column(Integer, ForeignKey("conversation_starters.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_proactive_logs_device_created", "device_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ProactiveTriggerLog(trigger='{self.trigger_type}', status='{self.status}', reason='{self.reason}')>"

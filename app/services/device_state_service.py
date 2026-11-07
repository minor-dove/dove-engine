"""Tracks presence + privacy mode per device. Privacy ON aborts any running stress session."""

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.core.security import ensure_utc
from app.models.device import Device
from app.models.device_state import DeviceState
from app.models.stress import StressSession


class DeviceStateService:

    @staticmethod
    def _get_or_create(db: Session, device_id: str) -> DeviceState:
        db.flush()  # make pending Device rows visible (sessions run with autoflush off)
        if not db.query(Device).filter(Device.id == device_id).first():
            db.add(Device(id=device_id, name="DOVE Desk Pet", status="online",
                          last_seen_at=datetime.now(timezone.utc)))
            db.flush()
        st = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
        if not st:
            st = DeviceState(device_id=device_id)
            db.add(st)
            db.flush()
        return st

    @staticmethod
    def set_presence(db: Session, device_id: str, present: bool, now: Optional[datetime] = None,
                     commit: bool = True) -> DeviceState:
        now = now or datetime.now(timezone.utc)
        st = DeviceStateService._get_or_create(db, device_id)
        if present and not st.present:
            st.present_since = now
        if not present:
            st.present_since = None
        st.present = present
        if present:
            st.last_present_at = now
        st.updated_at = now
        if commit:
            db.commit()
        return st

    @staticmethod
    def set_privacy(db: Session, device_id: str, on: bool, now: Optional[datetime] = None,
                    mqtt_publisher: Optional[Any] = None) -> DeviceState:
        from app.services.stress_service import StressService  # avoid import cycle
        now = now or datetime.now(timezone.utc)
        st = DeviceStateService._get_or_create(db, device_id)
        changed = st.privacy_on != on
        st.privacy_on = on
        if changed:
            st.privacy_since = now
        if on:
            # device sleeps: nobody is "present" for scoring purposes, running session ends
            st.present = False
            st.present_since = None
        st.updated_at = now
        db.commit()
        if on:
            for s in db.query(StressSession).filter(
                    StressSession.device_id == device_id, StressSession.status == "active").all():
                StressService.abort_session(db, s.id, mqtt_publisher=mqtt_publisher)
        return st

    @staticmethod
    def is_privacy_on(db: Session, device_id: str) -> bool:
        st = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
        return bool(st and st.privacy_on)

    @staticmethod
    def present_for_seconds(db: Session, device_id: str, now: datetime) -> float:
        """Seconds the user has been continuously present (0 if absent/unknown)."""
        st = db.query(DeviceState).filter(DeviceState.device_id == device_id).first()
        if not st or not st.present or not st.present_since:
            return 0.0
        return max(0.0, (now - ensure_utc(st.present_since)).total_seconds())

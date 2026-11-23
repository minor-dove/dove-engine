"""
Devices API Router.
Endpoints for device registration and status inspection.
"""

from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.models.device import Device
from app.schemas.app_api import DeviceStatusResponse
from app.services.app_overview_service import AppOverviewService
from app.schemas.device import DeviceCreate, DeviceUpdate, DeviceResponse

router = APIRouter(prefix="/devices", tags=["Devices"])


@router.get("", response_model=List[DeviceResponse])
def list_devices(db: Session = Depends(get_database)):
    """List registered DOVE desk pet hardware units."""
    return db.query(Device).all()


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def register_device(device_in: DeviceCreate, db: Session = Depends(get_database)):
    """Register a new DOVE device."""
    existing = db.query(Device).filter(Device.id == device_in.id).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device ID already registered")

    device = Device(
        id=device_in.id,
        name=device_in.name,
        firmware_version=device_in.firmware_version,
        status="online",
        last_seen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc)
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/{device_id}/status", response_model=DeviceStatusResponse)
def get_device_status(device_id: str, db: Session = Depends(get_database)):
    """Live status for the app: connection, presence, privacy (do-not-disturb) mode, today's check-ins.
    Always 200; `registered=false` / `connection=unknown` for ids the server has never seen."""
    return AppOverviewService.device_status(db, device_id)


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(device_id: str, db: Session = Depends(get_database)):
    """Get device details and status."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(device_id: str, device_in: DeviceUpdate, db: Session = Depends(get_database)):
    """Update device metadata."""
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    if device_in.name is not None:
        device.name = device_in.name
    if device_in.status is not None:
        device.status = device_in.status
    if device_in.firmware_version is not None:
        device.firmware_version = device_in.firmware_version

    db.commit()
    db.refresh(device)
    return device

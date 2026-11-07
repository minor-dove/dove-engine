"""
Reminders API Router.
Endpoints for creating, listing, updating, and acknowledging persistent reminders.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.schemas.reminder import ReminderCreate, ReminderUpdate, ReminderResponse
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/reminders", tags=["Reminders"])


@router.get("", response_model=List[ReminderResponse])
def list_reminders(
    status: Optional[str] = Query(default=None, description="Filter by status: pending, delivered, acknowledged, cancelled, failed"),
    limit: int = Query(default=50, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    db: Session = Depends(get_database)
):
    """List scheduled reminders."""
    return ReminderService.list_reminders(db=db, status=status, limit=limit, skip=skip)


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
def create_reminder(reminder_in: ReminderCreate, db: Session = Depends(get_database)):
    """Create a persistent scheduled reminder."""
    return ReminderService.create_reminder(db=db, reminder_in=reminder_in)


@router.get("/{reminder_id}", response_model=ReminderResponse)
def get_reminder(reminder_id: int, db: Session = Depends(get_database)):
    """Get reminder details."""
    reminder = ReminderService.get_reminder(db=db, reminder_id=reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    return reminder


@router.patch("/{reminder_id}", response_model=ReminderResponse)
def update_reminder(reminder_id: int, reminder_in: ReminderUpdate, db: Session = Depends(get_database)):
    """Update scheduled reminder."""
    reminder = ReminderService.update_reminder(db=db, reminder_id=reminder_id, reminder_in=reminder_in)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    return reminder


@router.post("/{reminder_id}/acknowledge", response_model=ReminderResponse)
def acknowledge_reminder(reminder_id: int, db: Session = Depends(get_database)):
    """Acknowledge receipt of a delivered reminder."""
    reminder = ReminderService.acknowledge_reminder(db=db, reminder_id=reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_reminder(reminder_id: int, db: Session = Depends(get_database)):
    """Cancel and delete reminder."""
    reminder = ReminderService.get_reminder(db=db, reminder_id=reminder_id)
    if not reminder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    db.delete(reminder)
    db.commit()
    return None

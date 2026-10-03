"""
User Preferences API Router.
Endpoints for managing quiet hours, cooldown duration, timezone, and routine times.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_database
from app.models.preference import UserPreference
from app.schemas.preference import UserPreferenceUpdate, UserPreferenceResponse

router = APIRouter(prefix="/preferences", tags=["Preferences"])


@router.get("", response_model=UserPreferenceResponse)
def get_preferences(db: Session = Depends(get_database)):
    """Retrieve current user preferences."""
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    if not pref:
        pref = UserPreference(id=1)
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


@router.put("", response_model=UserPreferenceResponse)
def update_preferences(pref_in: UserPreferenceUpdate, db: Session = Depends(get_database)):
    """Update user preferences."""
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    if not pref:
        pref = UserPreference(id=1)
        db.add(pref)

    for field, val in pref_in.model_dump(exclude_unset=True).items():
        setattr(pref, field, val)

    db.commit()
    db.refresh(pref)
    return pref

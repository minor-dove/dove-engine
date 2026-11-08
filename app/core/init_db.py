"""
Database initialization and starter seeding utility.
Populates standard non-judgmental starters and default user preferences.
"""

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.database import Base, engine, SessionLocal
from app.models.starter import ConversationStarter
from app.models.preference import UserPreference
from app.models.device import Device

DEFAULT_STARTERS = [
    # Sad starters
    {"category": "sad", "text": "Hey, just checking in. How are you doing today?"},
    {"category": "sad", "text": "Need a little company, or would you prefer some quiet time?"},
    {"category": "sad", "text": "Anything on your mind you'd like to share?"},

    # Angry starters
    {"category": "angry", "text": "Hey, everything okay? Want to talk about it?"},
    {"category": "angry", "text": "Want to take things one step at a time?"},
    {"category": "angry", "text": "Would you like to talk, take a break, or have some space?"},

    # Happy starters (for active conversation context)
    {"category": "happy", "text": "Something nice happen today?"},
    {"category": "happy", "text": "What's been the highlight of your day so far?"},
    {"category": "happy", "text": "Tell me one good thing about your day!"},

    # Neutral starters
    {"category": "neutral", "text": "Hey! How are you feeling today?"},
    {"category": "neutral", "text": "How's your day going so far?"},
    {"category": "neutral", "text": "Want to chat for a minute?"},

    # Morning routine starters
    {"category": "morning", "text": "Good morning! How are you feeling today?"},
    {"category": "morning", "text": "What's one thing you're looking forward to?"},

    # Midday routine starters
    {"category": "midday", "text": "Hey! How's your day going so far?"},
    {"category": "midday", "text": "Need help deciding what to tackle next?"},

    # Evening routine starters
    {"category": "evening", "text": "How did your day go?"},
    {"category": "evening", "text": "What's one good thing that happened today?"},

    # Night routine starters
    {"category": "night", "text": "Want to reflect on one thing you're proud of today?"},
    {"category": "night", "text": "Anything on your mind before you call it a night?"},
]


_INIT_LOCK_KEY = 727274  # arbitrary app-wide Postgres advisory lock id


def init_db(db: Session = None) -> None:
    """Creates tables and seeds default records if empty.

    On PostgreSQL this enables the pgvector extension first (create_all needs the `vector` type) and
    serialises concurrent starters (API + worker boot together in Docker) with an advisory lock.
    """
    if engine.dialect.name == "postgresql":
        with engine.connect() as lock_conn:
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _INIT_LOCK_KEY})
            try:
                lock_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                lock_conn.commit()
                _create_and_seed(db)
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _INIT_LOCK_KEY})
                lock_conn.commit()
    else:
        _create_and_seed(db)


def _create_and_seed(db: Session = None) -> None:
    # Ensure tables are created
    Base.metadata.create_all(bind=engine)

    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        # Seed default device if none exists
        existing_device = db.query(Device).filter(Device.id == "dove-esp32-01").first()
        if not existing_device:
            db.add(Device(
                id="dove-esp32-01",
                name="DOVE Desk Pet",
                status="online",
                firmware_version="v1.0.0",
                last_seen_at=datetime.now(timezone.utc)
            ))

        # Seed default user preferences
        existing_pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
        if not existing_pref:
            db.add(UserPreference(id=1))

        # Seed starter library
        for starter_data in DEFAULT_STARTERS:
            exists = db.query(ConversationStarter).filter(
                ConversationStarter.category == starter_data["category"],
                ConversationStarter.text == starter_data["text"]
            ).first()
            if not exists:
                db.add(ConversationStarter(
                    category=starter_data["category"],
                    text=starter_data["text"],
                    is_active=True,
                    usage_count=0
                ))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()

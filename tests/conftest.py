"""
Pytest configuration and common fixtures.
Configures an isolated SQLite database and mocked external services.
"""

import os
import sys
import pytest
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Set test environment variables
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GROQ_API_KEY"] = "gsk_test_placeholder"
os.environ["MOOD_EVENT_MAX_AGE_SECONDS"] = "1800"

from app.core.database import Base, get_db
from app.core.init_db import init_db
from app.main import app
from app.models.device import Device
from app.models.preference import UserPreference

# In-memory test engine using StaticPool so in-memory tables persist across connections
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    init_db(db)
    pref = db.query(UserPreference).filter(UserPreference.id == 1).first()
    if pref:
        pref.quiet_hours_start = "03:00"
        pref.quiet_hours_end = "03:00"
        db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session(clean_db):
    """Provides a fresh isolated database session for each test."""
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db_session):
    """Provides FastAPI test client overriding database dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class MockMQTTPublisher:
    def __init__(self):
        self.published_commands = []

    def publish_command(self, device_id: str, command_type: str, payload: dict) -> bool:
        self.published_commands.append({
            "device_id": device_id,
            "command_type": command_type,
            "payload": payload
        })
        return True


@pytest.fixture
def mock_mqtt():
    return MockMQTTPublisher()

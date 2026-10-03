"""
API Dependencies.
Provides database sessions without authentication requirements for local development.
"""

from typing import Generator
from sqlalchemy.orm import Session
from app.core.database import get_db

# Re-export get_db as standard dependency
get_database = get_db

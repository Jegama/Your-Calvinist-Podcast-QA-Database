"""
SQLAlchemy engine and session management.
"""

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator

from app.settings import get_settings


def get_engine(**options):
    """Create and return SQLAlchemy engine."""
    settings = get_settings()
    url = make_url(settings.DATABASE_URL)
    if url.drivername == "postgresql":
        # SQLAlchemy 2.1 defaults to psycopg 3 for unqualified URLs.
        url = url.set(drivername="postgresql+psycopg2")
    return create_engine(url, pool_pre_ping=True, **options)


# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    
    Usage:
        with get_session() as session:
            session.query(...)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

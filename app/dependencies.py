"""
FastAPI dependencies for authentication, database sessions, etc.
"""

from typing import Generator
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.orm import Session

from app.settings import get_settings
from app.db.engine import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency.
    
    Yields a database session and ensures it's closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """
    Verify the API key for protected endpoints.
    
    Raises HTTPException if the key is invalid.
    """
    settings = get_settings()
    
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: ADMIN_API_KEY not set"
        )
    
    if x_api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return x_api_key


def optional_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> bool:
    """
    Optional API key check - returns True if valid, False otherwise.
    Useful for endpoints that have different behavior for authenticated users.
    """
    settings = get_settings()
    
    if not settings.ADMIN_API_KEY or not x_api_key:
        return False
    
    return x_api_key == settings.ADMIN_API_KEY

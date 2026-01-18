"""
FastAPI dependencies for authentication, database sessions, etc.
"""

from typing import Generator, Optional
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


def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    Verify the API key for protected endpoints.
    
    Accepts either:
    - X-API-Key header (for manual/programmatic calls)
    - Authorization: Bearer <CRON_SECRET> header (for Vercel Cron)
    
    Raises HTTPException if no valid auth is provided.
    """
    settings = get_settings()
    
    # Check X-API-Key first (manual calls)
    if x_api_key:
        if settings.ADMIN_API_KEY and x_api_key == settings.ADMIN_API_KEY:
            return x_api_key
    
    # Check Authorization Bearer token (Vercel Cron)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]  # Remove "Bearer " prefix
        if settings.CRON_SECRET and token == settings.CRON_SECRET:
            return token
    
    # No valid auth provided
    if not settings.ADMIN_API_KEY and not settings.CRON_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: ADMIN_API_KEY or CRON_SECRET not set"
        )
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key or authorization token"
    )


def optional_api_key(x_api_key: str = Header(None, alias="X-API-Key")) -> bool:
    """
    Optional API key check - returns True if valid, False otherwise.
    Useful for endpoints that have different behavior for authenticated users.
    """
    settings = get_settings()
    
    if not settings.ADMIN_API_KEY or not x_api_key:
        return False
    
    return x_api_key == settings.ADMIN_API_KEY

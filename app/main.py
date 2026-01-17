"""
FastAPI application entry point.

Podcast Q&A API - Provides endpoints to query theological Q&A content
from the YourCalvinist Podcast with Keith Foskey.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.settings import get_settings
from app.routers import public_router, ingest_router

# Create FastAPI app
app = FastAPI(
    title="Podcast Q&A API",
    description="""
API for querying Q&A content from the YourCalvinist Podcast.

## Features
- Browse videos and their Q&A items
- Full-text search across questions and answers
- Filter by category, subcategory, and tags
- Automatic ingestion of new videos via cron

## Authentication
Public endpoints (GET) require no authentication.
Ingestion endpoints (POST) require an `X-API-Key` header.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
settings = get_settings()

# Default allowed origins (can be overridden via environment)
allowed_origins = [
    "http://localhost:3000",      # Local development
    "http://localhost:8000",      # Local API testing
    "https://keithfoskey.com",    # Production website
    "https://www.keithfoskey.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Include routers
app.include_router(public_router)
app.include_router(ingest_router)


@app.get("/", tags=["root"])
def root():
    """
    Root endpoint - API health check and info.
    """
    return {
        "name": "Podcast Q&A API",
        "version": "1.0.0",
        "status": "healthy",
        "docs": "/docs",
    }


@app.get("/health", tags=["root"])
def health_check():
    """
    Health check endpoint for monitoring.
    """
    return {"status": "ok"}

"""
FastAPI application entry point.

Podcast Q&A API - Provides endpoints to query theological Q&A content
from the YourCalvinist Podcast with Keith Foskey.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from mcp.server.transport_security import TransportSecuritySettings

from app.mcp_server import archive_mcp
from app.settings import get_settings
from app.routers import public_router, ingest_router


# Disable DNS rebinding protection — this is a public, open-access MCP server
# with read-only tools. Any MCP client should be able to connect.
transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
archive_mcp_http_app = archive_mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=transport_security,
)
archive_mcp_sse_app = archive_mcp.sse_app(sse_path="/", transport_security=transport_security)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with archive_mcp.session_manager.run():
        yield

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
    lifespan=lifespan,
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
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
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
        "mcp": {
            "streamable_http": "/mcp/",
            "sse": "/sse",
        },
    }


@app.get("/health", tags=["root"])
def health_check():
    """
    Health check endpoint for monitoring.
    """
    return {"status": "ok"}


@app.get("/sse/sse", include_in_schema=False)
def legacy_sse_path():
    return RedirectResponse("/sse/")


app.mount("/mcp", archive_mcp_http_app)
app.mount("/sse", archive_mcp_sse_app)  # legacy; prefer /mcp/

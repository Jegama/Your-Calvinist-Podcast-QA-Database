"""
Pydantic schemas for API request/response models.
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


# --- Video Schemas ---

class VideoBase(BaseModel):
    """Base video fields."""
    youtube_id: str
    title: Optional[str] = None
    channel_title: Optional[str] = None
    published_at: Optional[datetime] = None


class VideoOut(VideoBase):
    """Video response for list endpoints."""
    url: str
    status: str
    processed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class VideoDetailOut(VideoOut):
    """Video response with full details."""
    description: Optional[str] = None
    channel_id: Optional[str] = None
    
    class Config:
        from_attributes = True


class VideoSummaryOut(VideoBase):
    """Video with aggregated Q&A metadata for filtering/faceting."""
    qa_count: int = 0
    categories: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# --- Q&A Schemas ---

class QAItemBase(BaseModel):
    """Base Q&A fields."""
    timestamp_text: Optional[str] = None
    timestamp_seconds: int
    question: str
    category: Optional[str] = None
    subcategory: Optional[str] = None


class QAItemOut(QAItemBase):
    """Q&A response for list views (with preview)."""
    id: str
    answer_preview: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class QAItemDetailOut(QAItemBase):
    """Q&A response with full answer."""
    id: str
    answer: Optional[str] = None
    answer_preview: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    video_youtube_id: Optional[str] = None
    video_title: Optional[str] = None
    
    class Config:
        from_attributes = True


# --- Search Schemas ---

class SearchResult(BaseModel):
    """Single search result."""
    id: str
    youtube_id: str
    video_title: Optional[str] = None
    timestamp_text: Optional[str] = None
    timestamp_seconds: int
    question: str
    answer_preview: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    rank: Optional[float] = None


class SearchResponse(BaseModel):
    """Search endpoint response."""
    query: str
    total: int
    results: list[SearchResult]


class CitationOut(BaseModel):
    question_id: str
    youtube_id: Optional[str] = None
    video_title: Optional[str] = None
    timestamp_text: Optional[str] = None
    timestamp_seconds: Optional[int] = None
    question: str
    excerpt: Optional[str] = None
    source_url: Optional[str] = None


class AskSourceOut(BaseModel):
    id: str
    youtube_id: str
    video_title: Optional[str] = None
    timestamp_text: Optional[str] = None
    timestamp_seconds: int
    question: str
    answer_preview: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    rank: Optional[float] = None
    source_url: Optional[str] = None
    citation: CitationOut


class AskRequest(BaseModel):
    question: str = Field(min_length=2)
    mode: Literal["research", "answer"] = "answer"


class AskResponse(BaseModel):
    question: str
    mode: Literal["research", "answer"]
    answer: Optional[str] = None
    sources: list[AskSourceOut] = Field(default_factory=list)
    retrieved_candidates: int = 0
    used_sources: int = 0
    disclaimer: Optional[str] = None


# --- Ingest Schemas ---

class IngestCheckResponse(BaseModel):
    """Response from the check endpoint."""
    new_videos_found: int
    video_ids: list[str]
    message: str


class IngestRunResponse(BaseModel):
    """Response from run-one endpoint."""
    processed: bool
    youtube_id: Optional[str] = None
    title: Optional[str] = None
    questions_saved: int = 0
    error: Optional[str] = None
    message: str


class IngestQueueStats(BaseModel):
    """Queue statistics."""
    pending: int
    processing: int
    done: int
    failed: int
    total: int


# --- Generic Schemas ---

class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""
    total: int
    limit: int
    offset: int
    items: list


class ErrorResponse(BaseModel):
    """Error response."""
    detail: str

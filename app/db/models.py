"""
SQLAlchemy ORM models matching the Neon database schema.
"""

from sqlalchemy import (
    Column, String, Text, Integer, DateTime, ForeignKey, 
    UniqueConstraint, Index, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()


class Video(Base):
    """Represents a YouTube video."""
    __tablename__ = "videos"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    youtube_id = Column(Text, nullable=False, unique=True)
    url = Column(Text, nullable=False)
    title = Column(Text)
    channel_id = Column(Text)
    channel_title = Column(Text)
    published_at = Column(DateTime(timezone=True))
    description = Column(Text)
    processed_at = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False, default="pending")
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    qa_items = relationship("QAItem", back_populates="video", cascade="all, delete-orphan")
    transcript = relationship("Transcript", back_populates="video", uselist=False, cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Video(youtube_id={self.youtube_id}, title={self.title[:50] if self.title is not None else None})>"


class QAItem(Base):
    """Represents a question-answer pair from a video."""
    __tablename__ = "qa_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    timestamp_text = Column(Text)  # e.g., "23:45"
    timestamp_seconds = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    answer_preview = Column(Text)  # First 500 chars
    category = Column(Text)
    subcategory = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    video = relationship("Video", back_populates="qa_items")
    tags = relationship("Tag", secondary="qa_item_tags", back_populates="qa_items")
    
    __table_args__ = (
        UniqueConstraint("video_id", "timestamp_seconds", name="uq_video_timestamp"),
        Index("idx_qa_video_id", "video_id"),
    )
    
    def __repr__(self):
        return f"<QAItem(timestamp={self.timestamp_text}, question={self.question[:50] if self.question is not None else None})>"


class Tag(Base):
    """Represents a tag for categorizing Q&A items."""
    __tablename__ = "tags"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False, unique=True)
    
    # Relationships
    qa_items = relationship("QAItem", secondary="qa_item_tags", back_populates="tags")
    
    def __repr__(self):
        return f"<Tag(name={self.name})>"


class QAItemTag(Base):
    """Association table for QAItem and Tag many-to-many relationship."""
    __tablename__ = "qa_item_tags"
    
    qa_item_id = Column(UUID(as_uuid=True), ForeignKey("qa_items.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class Transcript(Base):
    """Stores raw transcript data separately from videos."""
    __tablename__ = "transcripts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, unique=True)
    raw_data = Column(JSONB)  # Array of {start: float, text: string}
    full_text = Column(Text)  # Optional concatenated text
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    # Relationships
    video = relationship("Video", back_populates="transcript")
    
    def __repr__(self):
        return f"<Transcript(video_id={self.video_id})>"


class IngestJob(Base):
    """Queue table for pending video processing jobs."""
    __tablename__ = "ingest_jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    youtube_id = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")  # pending | processing | done | failed
    attempts = Column(Integer, nullable=False, default=0)
    locked_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    
    __table_args__ = (
        Index("idx_jobs_status", "status"),
    )
    
    def __repr__(self):
        return f"<IngestJob(youtube_id={self.youtube_id}, status={self.status})>"

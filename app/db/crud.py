"""
Database CRUD operations for videos, Q&A items, tags, and transcripts.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.db.models import Video, QAItem, Tag, QAItemTag, Transcript, IngestJob


# --- Video Operations ---

def get_video_by_youtube_id(session: Session, youtube_id: str) -> Optional[Video]:
    """Get a video by its YouTube ID."""
    return session.query(Video).filter(Video.youtube_id == youtube_id).first()


def upsert_video(
    session: Session,
    youtube_id: str,
    url: str,
    title: Optional[str] = None,
    channel_id: Optional[str] = None,
    channel_title: Optional[str] = None,
    published_at: Optional[datetime] = None,
    description: Optional[str] = None,
    status: str = "pending",
) -> Video:
    """
    Insert or update a video record.
    Returns the Video object.
    """
    video = get_video_by_youtube_id(session, youtube_id)
    
    if video:
        # Update existing
        setattr(video, "url", url)
        if title is not None:
            setattr(video, "title", title)
        if channel_id is not None:
            setattr(video, "channel_id", channel_id)
        if channel_title is not None:
            setattr(video, "channel_title", channel_title)
        if published_at is not None:
            setattr(video, "published_at", published_at)
        if description is not None:
            setattr(video, "description", description)
        setattr(video, "status", status)
    else:
        # Insert new
        video = Video(
            youtube_id=youtube_id,
            url=url,
            title=title,
            channel_id=channel_id,
            channel_title=channel_title,
            published_at=published_at,
            description=description,
            status=status,
        )
        session.add(video)
    
    session.flush()  # Get the ID
    return video


def mark_video_processed(session: Session, video: Video, error: Optional[str] = None):
    """Mark a video as processed (or failed with error)."""
    setattr(video, "processed_at", datetime.now(timezone.utc))
    setattr(video, "status", "failed" if error else "processed")
    setattr(video, "error", error)
    session.flush()


# --- Transcript Operations ---

def upsert_transcript(
    session: Session,
    video_id,
    raw_data: list[dict],
    full_text: Optional[str] = None,
) -> Transcript:
    """Insert or update transcript for a video."""
    transcript = session.query(Transcript).filter(Transcript.video_id == video_id).first()
    
    if transcript:
        setattr(transcript, "raw_data", raw_data)
        setattr(transcript, "full_text", full_text)
    else:
        transcript = Transcript(
            video_id=video_id,
            raw_data=raw_data,
            full_text=full_text,
        )
        session.add(transcript)
    
    session.flush()
    return transcript


# --- Tag Operations ---

def get_or_create_tag(session: Session, name: str) -> Tag:
    """Get existing tag or create new one."""
    tag = session.query(Tag).filter(Tag.name == name).first()
    if not tag:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    return tag


def get_or_create_tags(session: Session, names: list[str]) -> list[Tag]:
    """Get or create multiple tags."""
    return [get_or_create_tag(session, name) for name in names]


# --- QA Item Operations ---

def upsert_qa_item(
    session: Session,
    video_id,
    timestamp_text: str,
    timestamp_seconds: int,
    question: str,
    answer: Optional[str] = None,
    answer_preview: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> QAItem:
    """
    Insert or update a Q&A item.
    Uniqueness is based on (video_id, timestamp_seconds).
    """
    qa_item = session.query(QAItem).filter(
        QAItem.video_id == video_id,
        QAItem.timestamp_seconds == timestamp_seconds
    ).first()
    
    if qa_item:
        # Update existing
        setattr(qa_item, "timestamp_text", timestamp_text)
        setattr(qa_item, "question", question)
        setattr(qa_item, "answer", answer)
        setattr(qa_item, "answer_preview", answer_preview)
        setattr(qa_item, "category", category)
        setattr(qa_item, "subcategory", subcategory)
    else:
        # Insert new
        qa_item = QAItem(
            video_id=video_id,
            timestamp_text=timestamp_text,
            timestamp_seconds=timestamp_seconds,
            question=question,
            answer=answer,
            answer_preview=answer_preview,
            category=category,
            subcategory=subcategory,
        )
        session.add(qa_item)
    
    session.flush()
    
    # Handle tags
    if tags:
        tag_objects = get_or_create_tags(session, tags)
        setattr(qa_item, "tags", tag_objects)
        session.flush()
    
    return qa_item


def bulk_upsert_qa_items(
    session: Session,
    video_id,
    items: list[dict],
) -> list[QAItem]:
    """
    Bulk insert/update Q&A items for a video.
    
    Each item should have:
    - timestamp_text: str
    - timestamp_seconds: int  
    - question: str
    - answer: Optional[str]
    - answer_preview: Optional[str]
    - category: Optional[str]
    - subcategory: Optional[str]
    - tags: Optional[list[str]]
    """
    results = []
    for item in items:
        qa = upsert_qa_item(
            session=session,
            video_id=video_id,
            timestamp_text=item["timestamp_text"],
            timestamp_seconds=item["timestamp_seconds"],
            question=item["question"],
            answer=item.get("answer"),
            answer_preview=item.get("answer_preview"),
            category=item.get("category"),
            subcategory=item.get("subcategory"),
            tags=item.get("tags"),
        )
        results.append(qa)
    return results


# --- Ingest Job Operations ---

def create_ingest_job(session: Session, youtube_id: str) -> IngestJob:
    """Create a new ingest job for a video."""
    job = IngestJob(youtube_id=youtube_id)
    session.add(job)
    session.flush()
    return job


def get_pending_job(session: Session) -> Optional[IngestJob]:
    """Get and lock one pending job atomically."""
    job = session.query(IngestJob).filter(
        IngestJob.status == "pending"
    ).order_by(IngestJob.created_at).first()
    
    if job:
        setattr(job, "status", "processing")
        setattr(job, "locked_at", datetime.now(timezone.utc))
        setattr(job, "attempts", job.attempts + 1)
        session.flush()
    
    return job


def complete_ingest_job(session: Session, job: IngestJob, error: Optional[str] = None):
    """Mark a job as done or failed."""
    if error:
        # Cast to int to satisfy type checker (SQLAlchemy columns are typed as Column[T])
        attempts: int = getattr(job, 'attempts', 0) or 0
        setattr(job, "status", "failed" if attempts >= 3 else "pending")
        setattr(job, "last_error", error)
        setattr(job, "locked_at", None)
    else:
        setattr(job, "status", "done")
    session.flush()

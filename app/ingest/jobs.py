"""
Ingest job management for the queue-based processing system.
"""

from typing import Optional
from datetime import datetime, timezone

from app.db.engine import get_session
from app.db import crud
from app.db.models import IngestJob, Video


def enqueue_video(youtube_id: str) -> bool:
    """
    Add a video to the ingest queue if not already known.
    
    Args:
        youtube_id: YouTube video ID
        
    Returns:
        True if enqueued, False if already exists
    """
    with get_session() as session:
        # Check if video already exists
        existing = crud.get_video_by_youtube_id(session, youtube_id)
        if existing:
            return False
        
        # Check if job already exists
        existing_job = session.query(IngestJob).filter(
            IngestJob.youtube_id == youtube_id
        ).first()
        if existing_job:
            return False
        
        # Create new job
        crud.create_ingest_job(session, youtube_id)
        return True


def get_and_lock_pending_job() -> Optional[str]:
    """
    Get one pending job and lock it for processing.
    
    Returns:
        YouTube ID of the locked job, or None if no jobs pending
    """
    with get_session() as session:
        job = crud.get_pending_job(session)
        if job is not None:
            youtube_id: str = getattr(job, 'youtube_id', '')
            if youtube_id:
                return youtube_id
    return None


def get_queue_stats() -> dict:
    """
    Get statistics about the ingest queue.
    
    Returns:
        Dict with counts by status
    """
    with get_session() as session:
        pending = session.query(IngestJob).filter(IngestJob.status == "pending").count()
        processing = session.query(IngestJob).filter(IngestJob.status == "processing").count()
        done = session.query(IngestJob).filter(IngestJob.status == "done").count()
        failed = session.query(IngestJob).filter(IngestJob.status == "failed").count()
        
        return {
            "pending": pending,
            "processing": processing,
            "done": done,
            "failed": failed,
            "total": pending + processing + done + failed,
        }

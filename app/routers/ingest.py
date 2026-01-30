"""
Protected ingestion endpoints for cron jobs and admin tasks.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, verify_api_key
from app.schemas import (
    IngestCheckResponse,
    IngestRunResponse,
    IngestQueueStats,
)
from app.db.models import Video, IngestJob
from app.db import crud
from app.youtube.playlist import get_playlist_video_ids
from app.ingest.pipeline import process_video
from app.ingest.jobs import get_queue_stats

router = APIRouter(
    prefix="/v1/ingest",
    tags=["ingest"],
    dependencies=[Depends(verify_api_key)],  # All routes require API key
)


# --- Cron endpoint (GET for Vercel Cron compatibility) ---

@router.get("/check", response_model=IngestCheckResponse)
def cron_check_for_new_videos(db: Session = Depends(get_db)):
    """
    GET endpoint for Vercel Cron to check for new videos.
    
    This is the same as POST /check but uses GET for Vercel Cron compatibility.
    Vercel Cron sends Authorization: Bearer <CRON_SECRET> header.
    """
    return _check_for_new_videos(db)


@router.post("/check", response_model=IngestCheckResponse)
def check_for_new_videos(db: Session = Depends(get_db)):
    """
    Check the playlist for new videos and enqueue them.
    
    This endpoint is called by the daily cron job.
    It fetches all video IDs from the configured playlist and
    creates ingest jobs for any videos not already in the database.
    
    Requires X-API-Key header.
    """
    return _check_for_new_videos(db)


# Video IDs to skip (known bad IDs, wrong playlist entries, etc.)
SKIP_VIDEO_IDS = {"4QpzXOyWDrE"}


def _check_for_new_videos(db: Session) -> IngestCheckResponse:
    """Internal implementation for check endpoint."""
    try:
        # Get all video IDs from playlist
        playlist_ids = get_playlist_video_ids()
        
        if not playlist_ids:
            return IngestCheckResponse(
                new_videos_found=0,
                video_ids=[],
                message="No videos found in playlist or API error"
            )
        
        # Find which ones are new or failed
        new_ids = []
        for youtube_id in playlist_ids:
            # Skip known bad video IDs
            if youtube_id in SKIP_VIDEO_IDS:
                continue
            
            # Check if video exists and is successfully processed
            existing_video = crud.get_video_by_youtube_id(db, youtube_id)
            if existing_video is not None:
                video_status = getattr(existing_video, 'status', '')
                if video_status == 'processed':
                    # Video already successfully processed, skip
                    continue
            
            # Check if job already exists and is pending/processing
            existing_job = db.query(IngestJob).filter(
                IngestJob.youtube_id == youtube_id,
                IngestJob.status.in_(['pending', 'processing'])
            ).first()
            if existing_job:
                # Job already queued or being processed, skip
                continue
            
            # Create new job (either new video or failed video that needs retry)
            crud.create_ingest_job(db, youtube_id)
            new_ids.append(youtube_id)
        
        db.commit()
        
        return IngestCheckResponse(
            new_videos_found=len(new_ids),
            video_ids=new_ids,
            message=f"Enqueued {len(new_ids)} video(s) for processing (new or failed)"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking playlist: {str(e)}"
        )


@router.post("/run-one", response_model=IngestRunResponse)
def run_one_job(
    skip_classification: bool = False,
    db: Session = Depends(get_db),
):
    """
    Process exactly one pending ingest job.
    
    This is designed to be serverless-friendly with bounded runtime.
    Can be called multiple times by cron to drain the queue.
    
    - **skip_classification**: If true, skip LLM classification (faster)
    
    Requires X-API-Key header.
    """
    try:
        # Get and lock one pending job
        job = crud.get_pending_job(db)
        db.commit()  # Commit the lock
        
        if not job:
            return IngestRunResponse(
                processed=False,
                message="No pending jobs in queue"
            )
        
        youtube_id: str = getattr(job, 'youtube_id', '')
        
        # Process the video
        result = process_video(
            youtube_id,
            skip_classification=skip_classification,
            verbose=False,  # Don't print to console in API context
        )
        
        # Update job status
        if result.success:
            crud.complete_ingest_job(db, job)
        else:
            crud.complete_ingest_job(db, job, error=result.error)
        
        db.commit()
        
        return IngestRunResponse(
            processed=True,
            youtube_id=result.youtube_id,
            title=result.title,
            questions_saved=result.questions_saved,
            error=result.error,
            message="Success" if result.success else f"Failed: {result.error}"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing job: {str(e)}"
        )


@router.get("/run-batch", response_model=list[IngestRunResponse])
def cron_run_batch_jobs(
    max_jobs: int = 5,
    skip_classification: bool = False,
    db: Session = Depends(get_db),
):
    """
    GET endpoint for Vercel Cron to process pending jobs.
    
    This is the same as POST /run-batch but uses GET for Vercel Cron compatibility.
    Vercel Cron sends Authorization: Bearer <CRON_SECRET> header.
    """
    return _run_batch_jobs(db, max_jobs, skip_classification)


@router.post("/run-batch", response_model=list[IngestRunResponse])
def run_batch_jobs(
    max_jobs: int = 5,
    skip_classification: bool = False,
    db: Session = Depends(get_db),
):
    """
    Process up to N pending ingest jobs.
    
    - **max_jobs**: Maximum number of jobs to process (default 5)
    - **skip_classification**: If true, skip LLM classification
    
    Requires X-API-Key header.
    """
    return _run_batch_jobs(db, max_jobs, skip_classification)


def _run_batch_jobs(
    db: Session,
    max_jobs: int = 5,
    skip_classification: bool = False,
) -> list[IngestRunResponse]:
    """Internal implementation for run-batch endpoint."""
    results = []
    
    for _ in range(max_jobs):
        try:
            job = crud.get_pending_job(db)
            db.commit()
            
            if not job:
                break
            
            youtube_id: str = getattr(job, 'youtube_id', '')
            
            result = process_video(
                youtube_id,
                skip_classification=skip_classification,
                verbose=False,
            )
            
            if result.success:
                crud.complete_ingest_job(db, job)
            else:
                crud.complete_ingest_job(db, job, error=result.error)
            
            db.commit()
            
            results.append(IngestRunResponse(
                processed=True,
                youtube_id=result.youtube_id,
                title=result.title,
                questions_saved=result.questions_saved,
                error=result.error,
                message="Success" if result.success else f"Failed: {result.error}"
            ))
            
        except Exception as e:
            db.rollback()
            results.append(IngestRunResponse(
                processed=False,
                error=str(e),
                message=f"Error: {str(e)}"
            ))
            break
    
    return results


@router.get("/queue", response_model=IngestQueueStats)
def get_queue_status(db: Session = Depends(get_db)):
    """
    Get the current status of the ingest queue.
    
    Requires X-API-Key header.
    """
    pending = db.query(IngestJob).filter(IngestJob.status == "pending").count()
    processing = db.query(IngestJob).filter(IngestJob.status == "processing").count()
    done = db.query(IngestJob).filter(IngestJob.status == "done").count()
    failed = db.query(IngestJob).filter(IngestJob.status == "failed").count()
    
    return IngestQueueStats(
        pending=pending,
        processing=processing,
        done=done,
        failed=failed,
        total=pending + processing + done + failed,
    )


@router.post("/reprocess/{youtube_id}", response_model=IngestRunResponse)
def reprocess_video(
    youtube_id: str,
    skip_classification: bool = False,
    db: Session = Depends(get_db),
):
    """
    Reprocess a specific video (useful for fixing errors or updating classifications).
    
    This will re-fetch the transcript and re-classify all Q&A items.
    
    Requires X-API-Key header.
    """
    # Check if video exists
    video = crud.get_video_by_youtube_id(db, youtube_id)
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found: {youtube_id}"
        )
    
    try:
        result = process_video(
            youtube_id,
            skip_classification=skip_classification,
            verbose=False,
        )
        
        db.commit()
        
        return IngestRunResponse(
            processed=True,
            youtube_id=result.youtube_id,
            title=result.title,
            questions_saved=result.questions_saved,
            error=result.error,
            message="Reprocessed successfully" if result.success else f"Failed: {result.error}"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reprocessing video: {str(e)}"
        )

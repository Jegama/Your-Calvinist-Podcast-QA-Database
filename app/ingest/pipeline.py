"""
Main ingestion pipeline - the "source of truth" for processing videos.

This module contains the core process_video() function that:
1. Fetches metadata from YouTube API
2. Parses timestamps from description
3. Fetches transcript
4. Stores raw transcript in database
5. Slices answers by time windows
6. Classifies Q&A items (optional)
7. Writes everything to database
"""

import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

from app.settings import get_settings
from app.db.engine import get_session
from app.db import crud
from app.db.models import Video, Transcript
from app.youtube.ids import get_video_id, build_video_url
from app.youtube.metadata import get_video_metadata
from app.youtube.transcripts import (
    TranscriptSegment,
    get_raw_transcript,
    transcript_to_raw_data,
    transcript_to_full_text,
)
from app.qa.timestamp_parser import parse_description_timestamps
from app.qa.answer_slicer import slice_answers_by_timestamps
from app.qa.classify import classify_question, load_categories


@dataclass
class ProcessResult:
    """Result of processing a single video."""
    youtube_id: str
    success: bool
    title: Optional[str] = None
    questions_found: int = 0
    questions_saved: int = 0
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


def process_video(
    youtube_id_or_url: str,
    skip_classification: bool = False,
    verbose: bool = True,
) -> ProcessResult:
    """
    Process a single YouTube video: extract Q&A and save to database.
    
    This is the main entry point for video processing, used by both
    the local backfill CLI and the online ingestion API.
    
    Args:
        youtube_id_or_url: YouTube video ID or full URL
        skip_classification: If True, skip LLM classification step
        verbose: If True, print progress messages
        
    Returns:
        ProcessResult with success status and counts
    """
    settings = get_settings()
    
    # Extract video ID if URL was provided
    try:
        youtube_id = get_video_id(youtube_id_or_url)
    except ValueError as e:
        return ProcessResult(
            youtube_id=youtube_id_or_url,
            success=False,
            error=str(e),
        )
    
    result = ProcessResult(youtube_id=youtube_id, success=False)
    
    if verbose:
        print(f"Processing: {youtube_id}")
    
    # Step 1: Fetch metadata
    if verbose:
        print("  Fetching metadata...")
    
    metadata = get_video_metadata(youtube_id)
    if not metadata:
        result.error = "Failed to fetch video metadata"
        return result
    
    result.title = metadata.title
    
    if verbose:
        print(f"  Title: {metadata.title}")
    
    # Step 2: Parse timestamps from description
    if verbose:
        print("  Parsing timestamps...")
    
    questions = parse_description_timestamps(metadata.description)
    result.questions_found = len(questions)
    
    if verbose:
        print(f"  Found {len(questions)} timestamps")
    
    if not questions:
        result.warnings.append("No timestamps found in description")
        # Continue anyway - we'll still save the video record
    
    # Step 3: Fetch transcript
    if verbose:
        print("  Fetching transcript...")
    
    transcript = get_raw_transcript(youtube_id)
    
    if not transcript:
        result.error = "Failed to fetch transcript"
        return result
    
    if verbose:
        print(f"  Transcript: {len(transcript)} segments")
    
    # Step 4: Slice answers
    qa_matches = []
    if questions and transcript:
        if verbose:
            print("  Slicing answers...")
        
        qa_matches = slice_answers_by_timestamps(
            questions,
            transcript,
            preview_length=settings.ANSWER_PREVIEW_LENGTH,
        )
    
    # Step 5: Classify (optional)
    if qa_matches and not skip_classification and settings.GEMINI_API_KEY:
        if verbose:
            print("  Classifying questions...")
        
        categories = load_categories()
        
        for i, qa in enumerate(qa_matches):
            if verbose:
                print(f"    [{i+1}/{len(qa_matches)}] {qa.question[:40]}...")
            
            classification = classify_question(
                qa.question,
                qa.answer,
                categories,
            )
            
            # Store classification in the match object
            if classification:
                qa.category = classification.category
                qa.subcategory = classification.subcategory
                qa.tags = classification.tags
                qa.passages = classification.passages
            else:
                qa.category = None
                qa.subcategory = None
                qa.tags = []
                qa.passages = []
    else:
        # No classification - set empty values
        for qa in qa_matches:
            qa.category = None
            qa.subcategory = None
            qa.tags = []
            qa.passages = []
    
    # Step 6: Save to database
    if verbose:
        print("  Saving to database...")
    
    try:
        with get_session() as session:
            # Upsert video record
            video = crud.upsert_video(
                session=session,
                youtube_id=youtube_id,
                url=build_video_url(youtube_id),
                title=metadata.title,
                channel_id=metadata.channel_id,
                channel_title=metadata.channel_title,
                published_at=metadata.published_at,
                description=metadata.description,
                status="processed",
            )
            
            # Save transcript
            crud.upsert_transcript(
                session=session,
                video_id=video.id,
                raw_data=transcript_to_raw_data(transcript),
                full_text=transcript_to_full_text(transcript),
            )
            
            # Save Q&A items
            for qa in qa_matches:
                crud.upsert_qa_item(
                    session=session,
                    video_id=video.id,
                    timestamp_text=qa.timestamp_text,
                    timestamp_seconds=qa.timestamp_seconds,
                    question=qa.question,
                    answer=qa.answer,
                    answer_preview=qa.answer_preview,
                    category=qa.category,
                    subcategory=qa.subcategory,
                    tags=qa.tags or [],
                    passages=qa.passages or [],
                )
            
            # Mark as processed
            crud.mark_video_processed(session, video)
            
            result.questions_saved = len(qa_matches)
        
        result.success = True
        
        if verbose:
            print(f"  ✓ Saved {len(qa_matches)} Q&A items")
        
    except Exception as e:
        result.error = f"Database error: {str(e)}"
        if verbose:
            print(f"  ✗ Error: {e}")
    
    return result


def process_video_from_job(youtube_id: str, skip_classification: bool = False) -> ProcessResult:
    """
    Process a video from an ingest job, updating job status.
    
    Args:
        youtube_id: YouTube video ID
        skip_classification: If True, skip LLM classification
        
    Returns:
        ProcessResult
    """
    result = process_video(youtube_id, skip_classification=skip_classification)
    
    # Update job status in database
    with get_session() as session:
        from app.db.models import IngestJob
        
        job = session.query(IngestJob).filter(
            IngestJob.youtube_id == youtube_id,
            IngestJob.status == "processing"
        ).first()
        
        if job:
            if result.success:
                crud.complete_ingest_job(session, job)
            else:
                crud.complete_ingest_job(session, job, error=result.error)

    return result


def reprocess_from_stored_transcript(
    youtube_id: str,
    skip_classification: bool = False,
    verbose: bool = True,
) -> ProcessResult:
    """
    Re-process a video using its stored transcript and description.

    Avoids YouTube API hits entirely. Useful for re-classifying with
    updated prompts (e.g., adding passages field) or fixing classification.

    Requires the video to already exist with a stored transcript.
    """
    settings = get_settings()
    result = ProcessResult(youtube_id=youtube_id, success=False)

    try:
        with get_session() as session:
            video = session.query(Video).filter(
                Video.youtube_id == youtube_id,
            ).first()

            if not video:
                result.error = "Video not found in database"
                return result

            result.title = video.title

            transcript_row = session.query(Transcript).filter(
                Transcript.video_id == video.id,
            ).first()

            if not transcript_row or not transcript_row.raw_data:
                result.error = "No stored transcript found"
                return result

            if verbose:
                print(f"Re-processing: {youtube_id} ({video.title})")

            # Convert stored JSONB back to TranscriptSegment objects
            segments = [
                TranscriptSegment(
                    start=seg["start"],
                    duration=seg.get("duration", 0.0),
                    text=seg["text"],
                )
                for seg in transcript_row.raw_data
            ]

            # Parse timestamps from stored description
            description = video.description or ""
            questions = parse_description_timestamps(description)
            result.questions_found = len(questions)

            if verbose:
                print(f"  Found {len(questions)} timestamps, {len(segments)} transcript segments")

            if not questions:
                result.warnings.append("No timestamps found in description")

            # Slice answers
            qa_matches = []
            if questions and segments:
                qa_matches = slice_answers_by_timestamps(
                    questions,
                    segments,
                    preview_length=settings.ANSWER_PREVIEW_LENGTH,
                )

            # Classify
            if qa_matches and not skip_classification and settings.GEMINI_API_KEY:
                if verbose:
                    print("  Classifying questions...")

                categories = load_categories()

                for i, qa in enumerate(qa_matches):
                    if verbose:
                        print(f"    [{i+1}/{len(qa_matches)}] {qa.question[:40]}...")

                    classification = classify_question(
                        qa.question,
                        qa.answer,
                        categories,
                    )

                    if classification:
                        qa.category = classification.category
                        qa.subcategory = classification.subcategory
                        qa.tags = classification.tags
                        qa.passages = classification.passages
                    else:
                        qa.category = None
                        qa.subcategory = None
                        qa.tags = []
                        qa.passages = []
            else:
                for qa in qa_matches:
                    qa.category = None
                    qa.subcategory = None
                    qa.tags = []
                    qa.passages = []

            # Upsert Q&A items
            for qa in qa_matches:
                crud.upsert_qa_item(
                    session=session,
                    video_id=video.id,
                    timestamp_text=qa.timestamp_text,
                    timestamp_seconds=qa.timestamp_seconds,
                    question=qa.question,
                    answer=qa.answer,
                    answer_preview=qa.answer_preview,
                    category=qa.category,
                    subcategory=qa.subcategory,
                    tags=qa.tags or [],
                    passages=qa.passages or [],
                )

            crud.mark_video_processed(session, video)
            result.questions_saved = len(qa_matches)

        result.success = True

        if verbose:
            print(f"  ✓ Saved {len(qa_matches)} Q&A items")

    except Exception as e:
        result.error = f"Reprocess error: {str(e)}"
        if verbose:
            print(f"  ✗ Error: {e}")

    return result


def reprocess_all_from_stored(
    skip_classification: bool = False,
    limit: Optional[int] = None,
    delay: float = 1.0,
    verbose: bool = True,
) -> list[ProcessResult]:
    """Reprocess all processed videos from stored transcripts."""
    with get_session() as session:
        query = session.query(Video.youtube_id).filter(
            Video.status == "processed",
        ).order_by(Video.published_at.desc())

        youtube_ids = [row[0] for row in query.all()]

    if limit:
        youtube_ids = youtube_ids[:limit]

    if verbose:
        print(f"Re-processing {len(youtube_ids)} videos from stored transcripts\n")

    results = []
    for i, yt_id in enumerate(youtube_ids, 1):
        if verbose:
            print(f"[{i}/{len(youtube_ids)}]", end=" ")

        r = reprocess_from_stored_transcript(
            yt_id,
            skip_classification=skip_classification,
            verbose=verbose,
        )
        results.append(r)

        if i < len(youtube_ids) and delay > 0:
            time.sleep(delay)

    return results

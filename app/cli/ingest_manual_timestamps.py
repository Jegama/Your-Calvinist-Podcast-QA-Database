#!/usr/bin/env python3
"""
Ingest videos with manually extracted timestamps.

This script processes videos that didn't originally have timestamps in their
descriptions, but now have manually extracted timestamps (e.g., from an LLM).

The script:
1. Reads timestamp files from a directory (e.g., parse-older-videos/inferred-questions/)
2. Updates the video description with the new timestamps
3. Re-processes the video through the normal pipeline
4. Saves Q&A items to the database

Usage:
    python -m app.cli.ingest_manual_timestamps                    # Process all in parse-older-videos/inferred-questions/
    python -m app.cli.ingest_manual_timestamps --dir my-folder/   # Custom directory
    python -m app.cli.ingest_manual_timestamps --limit 2          # Process only 2 videos
    python -m app.cli.ingest_manual_timestamps --skip-classification  # Skip LLM classification
    python -m app.cli.ingest_manual_timestamps --dry-run          # Don't save to database
"""

import argparse
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

from app.settings import get_settings
from app.youtube.ids import get_video_id, build_video_url
from app.youtube.metadata import get_video_metadata
from app.youtube.transcripts import (
    get_raw_transcript,
    transcript_to_raw_data,
    transcript_to_full_text,
)
from app.qa.timestamp_parser import parse_description_timestamps
from app.qa.answer_slicer import slice_answers_by_timestamps
from app.qa.classify import classify_question, load_categories
from app.db.engine import get_session
from app.db import crud


@dataclass
class IngestStats:
    """Statistics for the manual ingest run."""
    total: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_questions: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    
    def print_summary(self):
        """Print a summary of the ingest run."""
        print("\n" + "=" * 60)
        print("MANUAL TIMESTAMP INGEST SUMMARY")
        print("=" * 60)
        print(f"Total files found:       {self.total}")
        print(f"Processed:               {self.processed}")
        print(f"  Successful:            {self.successful}")
        print(f"  Failed:                {self.failed}")
        print(f"Skipped:                 {self.skipped}")
        print(f"Total Q&A items saved:   {self.total_questions}")
        
        if self.errors:
            print("\nErrors:")
            for video_id, error in self.errors:
                print(f"  {video_id}: {error}")


def find_timestamp_files(directory: str) -> list[Path]:
    """
    Find all timestamp files in a directory.
    
    Args:
        directory: Path to directory containing timestamp files
        
    Returns:
        List of Path objects for files ending in _description.txt or _decription.txt (typo variant)
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        print(f"Error: Directory not found: {directory}")
        return []
    
    # Handle both correct spelling and typo variant
    files = list(dir_path.glob("*_description.txt")) + list(dir_path.glob("*_decription.txt"))
    return sorted(files)


def extract_video_id_from_filename(filename: str) -> str:
    """
    Extract YouTube video ID from filename.
    
    Examples:
        "Q8rfyMrjlnI_description.txt" -> "Q8rfyMrjlnI"
        "ucjegR-jiYo_decription.txt" -> "ucjegR-jiYo"
    """
    # Remove _description.txt or _decription.txt suffix
    name = filename.replace("_description.txt", "").replace("_decription.txt", "")
    return name


def read_manual_timestamps(file_path: Path) -> str:
    """
    Read the manually extracted timestamps from a file.
    
    Args:
        file_path: Path to timestamp file
        
    Returns:
        The full content of the file (should contain "Questions and Timestamps:" section)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def process_video_with_manual_timestamps(
    video_id: str,
    manual_timestamps: str,
    skip_classification: bool = False,
    verbose: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Process a video using manually extracted timestamps.
    
    This mimics the normal pipeline but uses the manual timestamps instead
    of fetching the description from YouTube.
    
    Args:
        video_id: YouTube video ID
        manual_timestamps: Text content with timestamps (replaces description)
        skip_classification: If True, skip LLM classification
        verbose: If True, print progress messages
        dry_run: If True, don't save to database
        
    Returns:
        Dictionary with success status and counts
    """
    settings = get_settings()
    
    result = {
        "youtube_id": video_id,
        "success": False,
        "title": None,
        "questions_found": 0,
        "questions_saved": 0,
        "error": None,
    }
    
    if verbose:
        print(f"  Processing: {video_id}")
    
    # Step 1: Fetch original metadata (we need title, channel, etc.)
    if verbose:
        print("    Fetching metadata...")
    
    metadata = get_video_metadata(video_id)
    if not metadata:
        result["error"] = "Failed to fetch video metadata"
        return result
    
    result["title"] = metadata.title
    
    if verbose:
        print(f"    Title: {metadata.title}")
    
    # Step 2: Parse timestamps from the MANUAL text
    if verbose:
        print("    Parsing manual timestamps...")
    
    questions = parse_description_timestamps(manual_timestamps)
    result["questions_found"] = len(questions)
    
    if verbose:
        print(f"    Found {len(questions)} timestamps")
    
    if not questions:
        result["error"] = "No timestamps found in manual file"
        return result
    
    # Step 3: Fetch transcript
    if verbose:
        print("    Fetching transcript...")
    
    transcript = get_raw_transcript(video_id)
    
    if not transcript:
        result["error"] = "Failed to fetch transcript"
        return result
    
    if verbose:
        print(f"    Transcript: {len(transcript)} segments")
    
    # Step 4: Slice answers
    if verbose:
        print("    Slicing answers...")
    
    qa_matches = slice_answers_by_timestamps(
        questions,
        transcript,
        preview_length=settings.ANSWER_PREVIEW_LENGTH,
    )
    
    if not qa_matches:
        result["error"] = "Failed to slice answers from transcript"
        return result
    
    # Step 5: Classify (optional)
    if not skip_classification and settings.GEMINI_API_KEY:
        if verbose:
            print("    Classifying questions...")
        
        categories = load_categories()
        
        for i, qa in enumerate(qa_matches):
            if verbose:
                print(f"      [{i+1}/{len(qa_matches)}] {qa.question[:40]}...")
            
            classification = classify_question(
                qa.question,
                qa.answer,
                categories,
            )
            
            if classification:
                qa.category = classification.category
                qa.subcategory = classification.subcategory
                qa.tags = classification.tags
            else:
                qa.category = None
                qa.subcategory = None
                qa.tags = []
    else:
        for qa in qa_matches:
            qa.category = None
            qa.subcategory = None
            qa.tags = []
    
    # Step 6: Save to database (unless dry run)
    if dry_run:
        if verbose:
            print(f"    DRY RUN - Would save {len(qa_matches)} Q&A items")
        result["success"] = True
        result["questions_saved"] = len(qa_matches)
        return result
    
    if verbose:
        print("    Saving to database...")
    
    try:
        with get_session() as session:
            # Upsert video record with UPDATED description that includes timestamps
            updated_description = metadata.description + "\n\n" + manual_timestamps
            
            video = crud.upsert_video(
                session=session,
                youtube_id=video_id,
                url=build_video_url(video_id),
                title=metadata.title,
                channel_id=metadata.channel_id,
                channel_title=metadata.channel_title,
                published_at=metadata.published_at,
                description=updated_description,  # Include manual timestamps
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
                )
            
            # Mark as processed
            crud.mark_video_processed(session, video)
            
            result["questions_saved"] = len(qa_matches)
        
        result["success"] = True
        
        if verbose:
            print(f"    ✓ Saved {len(qa_matches)} Q&A items")
        
    except Exception as e:
        result["error"] = f"Database error: {str(e)}"
        if verbose:
            print(f"    ✗ Error: {e}")
    
    return result


def run_manual_ingest(
    directory: str,
    skip_classification: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    delay: float = 1.0,
) -> IngestStats:
    """
    Process all timestamp files in a directory.
    
    Args:
        directory: Directory containing timestamp files
        skip_classification: If True, skip LLM classification
        limit: Maximum number of videos to process
        dry_run: If True, don't save to database
        delay: Seconds to wait between videos
        
    Returns:
        IngestStats with results
    """
    stats = IngestStats()
    
    # Find all timestamp files
    files = find_timestamp_files(directory)
    stats.total = len(files)
    
    if not files:
        print(f"No timestamp files found in {directory}")
        return stats
    
    if limit:
        files = files[:limit]
        print(f"Processing {len(files)} of {stats.total} videos (limit={limit})")
    else:
        print(f"Processing {len(files)} videos from {directory}")
    
    print()
    
    for i, file_path in enumerate(files, 1):
        try:
            video_id = extract_video_id_from_filename(file_path.name)
        except Exception as e:
            print(f"[{i}/{len(files)}] SKIP: Invalid filename - {file_path.name}")
            stats.skipped += 1
            continue
        
        print(f"[{i}/{len(files)}] {video_id}")
        
        # Read manual timestamps
        try:
            manual_timestamps = read_manual_timestamps(file_path)
        except Exception as e:
            print(f"  ✗ Error reading file: {e}")
            stats.failed += 1
            stats.errors.append((video_id, f"File read error: {e}"))
            continue
        
        # Process the video
        result = process_video_with_manual_timestamps(
            video_id=video_id,
            manual_timestamps=manual_timestamps,
            skip_classification=skip_classification,
            verbose=True,
            dry_run=dry_run,
        )
        
        stats.processed += 1
        
        if result["success"]:
            stats.successful += 1
            stats.total_questions += result["questions_saved"]
        else:
            stats.failed += 1
            stats.errors.append((video_id, result["error"] or "Unknown error"))
        
        # Rate limiting
        if i < len(files) and delay > 0:
            time.sleep(delay)
    
    return stats


def main():
    """Main entry point for the manual timestamp ingest CLI."""
    parser = argparse.ArgumentParser(
        description="Ingest videos with manually extracted timestamps."
    )
    parser.add_argument(
        "--dir", "-d",
        default="parse-older-videos/inferred-questions",
        help="Directory containing timestamp files (default: parse-older-videos/inferred-questions)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Maximum number of videos to process"
    )
    parser.add_argument(
        "--skip-classification",
        action="store_true",
        help="Skip LLM classification step"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save to database, just show what would be processed"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between videos (default: 1.0)"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Just check configuration and exit"
    )
    
    args = parser.parse_args()
    
    # Check configuration
    settings = get_settings()
    missing = settings.validate()
    
    if missing:
        print("Configuration errors:")
        for key in missing:
            print(f"  Missing: {key}")
        sys.exit(1)
    
    if args.check_config:
        print("Configuration OK!")
        print(f"  DATABASE_URL: {'set' if settings.DATABASE_URL else 'not set'}")
        print(f"  GOOGLE_API_KEY: {'set' if settings.GOOGLE_API_KEY else 'not set'}")
        print(f"  GEMINI_API_KEY: {'set' if settings.GEMINI_API_KEY else 'not set'}")
        sys.exit(0)
    
    # Run manual ingest
    try:
        stats = run_manual_ingest(
            directory=args.dir,
            skip_classification=args.skip_classification,
            limit=args.limit,
            dry_run=args.dry_run,
            delay=args.delay,
        )
        stats.print_summary()
        
        # Exit with error if any failures
        sys.exit(1 if stats.failed > 0 else 0)
        
    except KeyboardInterrupt:
        print("\n\nIngest interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Local backfill script for processing existing videos.

Reads video URLs from a text file and processes each one,
extracting Q&A pairs and saving to the Neon database.

Usage:
    python -m app.cli.backfill                          # Use playlist_videos.txt
    python -m app.cli.backfill --file my_videos.txt     # Custom file
    python -m app.cli.backfill --limit 5                # Process only 5 videos
    python -m app.cli.backfill --skip-classification    # Skip LLM classification
    python -m app.cli.backfill --dry-run                # Don't save to database
"""

import argparse
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

from app.settings import get_settings
from app.youtube.ids import get_video_id
from app.ingest.pipeline import process_video, ProcessResult, reprocess_all_from_stored
from app.db.engine import get_session
from app.db import crud


@dataclass
class BackfillStats:
    """Statistics for the backfill run."""
    total: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_questions: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    
    def print_summary(self):
        """Print a summary of the backfill run."""
        print("\n" + "=" * 60)
        print("BACKFILL SUMMARY")
        print("=" * 60)
        print(f"Total videos in file:    {self.total}")
        print(f"Processed:               {self.processed}")
        print(f"  Successful:            {self.successful}")
        print(f"  Failed:                {self.failed}")
        print(f"Skipped:                 {self.skipped}")
        print(f"Total Q&A items saved:   {self.total_questions}")
        
        if self.errors:
            print("\nErrors:")
            for video_id, error in self.errors:
                print(f"  {video_id}: {error}")


def read_video_urls(filepath: str) -> list[str]:
    """
    Read video URLs from a text file.
    
    Args:
        filepath: Path to text file with one URL per line
        
    Returns:
        List of URLs (empty lines and comments ignored)
    """
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}")
        return []
    
    urls = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if line and not line.startswith('#'):
                urls.append(line)
    
    return urls


def run_backfill(
    urls: list[str],
    skip_classification: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    delay: float = 1.0,
    skip_processed: bool = False,
) -> BackfillStats:
    """
    Process a list of video URLs.
    
    Args:
        urls: List of YouTube video URLs
        skip_classification: If True, skip LLM classification
        limit: Maximum number of videos to process
        dry_run: If True, don't save to database
        delay: Seconds to wait between videos
        skip_processed: If True, skip videos that are already processed
        
    Returns:
        BackfillStats with results
    """
    stats = BackfillStats(total=len(urls))
    
    if limit:
        urls = urls[:limit]
        print(f"Processing {len(urls)} of {stats.total} videos (limit={limit})")
    else:
        print(f"Processing {len(urls)} videos")
    
    print()
    
    for i, url in enumerate(urls, 1):
        try:
            video_id = get_video_id(url)
        except ValueError as e:
            print(f"[{i}/{len(urls)}] SKIP: Invalid URL - {url}")
            stats.skipped += 1
            continue
        
        print(f"[{i}/{len(urls)}] {video_id}")
        
        # Check if already processed (if requested)
        if skip_processed:
            with get_session() as session:
                existing = crud.get_video_by_youtube_id(session, video_id)
                if existing and getattr(existing, 'status', '') == 'processed':
                    print("  Already processed - skipping")
                    stats.skipped += 1
                    continue
        
        if dry_run:
            print("  (dry run - skipping)")
            stats.skipped += 1
            continue
        
        result = process_video(
            video_id,
            skip_classification=skip_classification,
            verbose=True,
        )
        
        stats.processed += 1
        
        if result.success:
            stats.successful += 1
            stats.total_questions += result.questions_saved
        else:
            stats.failed += 1
            stats.errors.append((video_id, result.error or "Unknown error"))
        
        # Rate limiting
        if i < len(urls) and delay > 0:
            time.sleep(delay)
    
    return stats


def main():
    """Main entry point for the backfill CLI."""
    parser = argparse.ArgumentParser(
        description="Backfill Q&A data from YouTube videos to database."
    )
    parser.add_argument(
        "--file", "-f",
        default="playlist_videos.txt",
        help="Path to text file with video URLs (default: playlist_videos.txt)"
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
        "--skip-processed",
        action="store_true",
        help="Skip videos that are already successfully processed"
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
        "--from-stored",
        action="store_true",
        help="Re-process videos using stored transcripts (no YouTube API calls). "
             "Use this for re-classification with updated prompts."
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Just check configuration and exit"
    )
    
    args = parser.parse_args()

    # --dry-run has no effect in --from-stored mode (reprocess writes directly
    # to the existing video rows). Reject the combination up front rather than
    # silently mutating the DB.
    if args.from_stored and args.dry_run:
        print(
            "Error: --dry-run is not supported with --from-stored "
            "(reprocessing writes directly to existing rows)."
        )
        sys.exit(2)

    # Check configuration
    settings = get_settings()
    # --from-stored only needs DATABASE_URL (and optionally GEMINI_API_KEY),
    # not YOUTUBE_API_KEY since it skips YouTube API calls entirely.
    if args.from_stored:
        if not settings.DATABASE_URL:
            print("Configuration error: Missing DATABASE_URL")
            sys.exit(1)
    else:
        missing = settings.validate()
        if missing:
            print("Configuration errors:")
            for key in missing:
                print(f"  Missing: {key}")
            sys.exit(1)
    
    if args.check_config:
        print("Configuration OK!")
        print(f"  DATABASE_URL: {'set' if settings.DATABASE_URL else 'not set'}")
        print(f"  YOUTUBE_API_KEY: {'set' if settings.YOUTUBE_API_KEY else 'not set'}")
        print(f"  GEMINI_API_KEY: {'set' if settings.GEMINI_API_KEY else 'not set'}")
        sys.exit(0)
    
    if args.from_stored:
        # Re-process from stored transcripts (no YouTube API calls)
        try:
            results = reprocess_all_from_stored(
                skip_classification=args.skip_classification,
                limit=args.limit,
                delay=args.delay,
                verbose=True,
            )

            # Print summary
            successful = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            total_qs = sum(r.questions_saved for r in results)

            print("\n" + "=" * 60)
            print("RE-PROCESS SUMMARY (from stored transcripts)")
            print("=" * 60)
            print(f"Total videos:            {len(results)}")
            print(f"  Successful:            {successful}")
            print(f"  Failed:                {failed}")
            print(f"Total Q&A items saved:   {total_qs}")

            if failed:
                print("\nErrors:")
                for r in results:
                    if not r.success:
                        print(f"  {r.youtube_id}: {r.error}")

            sys.exit(1 if failed > 0 else 0)

        except KeyboardInterrupt:
            print("\n\nRe-process interrupted by user.")
            sys.exit(130)
    else:
        # Read URLs
        urls = read_video_urls(args.file)
        if not urls:
            print(f"No URLs found in {args.file}")
            sys.exit(1)

        # Run backfill
        try:
            stats = run_backfill(
                urls=urls,
                skip_classification=args.skip_classification,
                limit=args.limit,
                dry_run=args.dry_run,
                delay=args.delay,
                skip_processed=args.skip_processed,
            )
            stats.print_summary()

            # Exit with error if any failures
            sys.exit(1 if stats.failed > 0 else 0)

        except KeyboardInterrupt:
            print("\n\nBackfill interrupted by user.")
            sys.exit(130)


if __name__ == "__main__":
    main()

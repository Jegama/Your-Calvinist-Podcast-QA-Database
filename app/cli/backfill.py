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
from app.ingest.pipeline import process_video, ProcessResult


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
) -> BackfillStats:
    """
    Process a list of video URLs.
    
    Args:
        urls: List of YouTube video URLs
        skip_classification: If True, skip LLM classification
        limit: Maximum number of videos to process
        dry_run: If True, don't save to database
        delay: Seconds to wait between videos
        
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
        )
        stats.print_summary()
        
        # Exit with error if any failures
        sys.exit(1 if stats.failed > 0 else 0)
        
    except KeyboardInterrupt:
        print("\n\nBackfill interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()

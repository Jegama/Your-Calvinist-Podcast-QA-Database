"""
Script to export transcripts and descriptions for videos.
"""

import os
from app.youtube.ids import get_video_id
from app.youtube.metadata import get_video_metadata
from app.youtube.transcripts import get_raw_transcript, transcript_to_full_text


def export_video_data(youtube_url: str, output_dir: str = "exports"):
    """
    Export transcript and description for a video.
    
    Args:
        youtube_url: Full YouTube URL or video ID
        output_dir: Directory to save exports
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Extract video ID
    video_id = get_video_id(youtube_url)
    if not video_id:
        print(f"❌ Could not extract video ID from: {youtube_url}")
        return False
    
    print(f"📹 Processing video: {video_id}")
    
    # Fetch metadata
    print("  ⬇️  Fetching metadata...")
    metadata = get_video_metadata(video_id)
    if not metadata:
        print(f"  ❌ Could not fetch metadata for {video_id}")
        return False
    
    print(f"  ✅ Title: {metadata.title}")
    
    # Fetch transcript
    print("  ⬇️  Fetching transcript...")
    transcript_segments = get_raw_transcript(video_id)
    if not transcript_segments:
        print(f"  ❌ Could not fetch transcript for {video_id}")
        return False
    
    print(f"  ✅ Transcript: {len(transcript_segments)} segments")
    
    # Save description
    desc_filename = f"{video_id}_description.txt"
    desc_path = os.path.join(output_dir, desc_filename)
    with open(desc_path, 'w', encoding='utf-8') as f:
        f.write(f"Video: {metadata.title}\n")
        f.write(f"URL: https://www.youtube.com/watch?v={video_id}\n")
        f.write(f"Published: {metadata.published_at}\n")
        f.write(f"\n{'='*80}\n\n")
        f.write(metadata.description)
    print(f"  💾 Saved description: {desc_path}")
    
    # Save transcript
    transcript_filename = f"{video_id}_transcript.txt"
    transcript_path = os.path.join(output_dir, transcript_filename)
    full_transcript = transcript_to_full_text(transcript_segments)
    
    with open(transcript_path, 'w', encoding='utf-8') as f:
        f.write(f"Video: {metadata.title}\n")
        f.write(f"URL: https://www.youtube.com/watch?v={video_id}\n")
        f.write(f"Published: {metadata.published_at}\n")
        f.write(f"\n{'='*80}\n\n")
        # Write timestamped segments
        for seg in transcript_segments:
            minutes = int(seg.start // 60)
            seconds = int(seg.start % 60)
            f.write(f"[{minutes:02d}:{seconds:02d}] {seg.text}\n")
        f.write(f"\n{'='*80}\n\nFULL TEXT (No timestamps):\n\n")
        f.write(full_transcript)
    print(f"  💾 Saved transcript: {transcript_path}")
    
    return True


def main():
    """Main execution."""
    print("\n🚀 Starting transcript export...\n")
    
    # 1. Export latest video
    print("=" * 80)
    print("1️⃣  LATEST VIDEO")
    print("=" * 80)
    latest_video = "https://www.youtube.com/watch?v=qS8kiCWbZy0"
    export_video_data(latest_video)
    
    print("\n")
    
    # 2. Export videos without Q&A
    print("=" * 80)
    print("2️⃣  VIDEOS WITHOUT Q&A")
    print("=" * 80)
    
    videos_without_qa = [
        "Q8rfyMrjlnI",
        "ucjegR-jiYo",
        "kCp0tkR7YYU",
        "6Ih9uEGeJBI",
    ]
    
    for video_id in videos_without_qa:
        print()
        export_video_data(video_id)
    
    print("\n" + "=" * 80)
    print("✅ Export complete! Check the 'exports' directory.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

"""
Fetch transcripts from YouTube videos.
"""

from typing import Optional
from dataclasses import dataclass
from youtube_transcript_api import YouTubeTranscriptApi


@dataclass
class TranscriptSegment:
    """A single segment of transcript with timing."""
    start: float  # Start time in seconds
    duration: float
    text: str


def get_raw_transcript(video_id: str) -> Optional[list[TranscriptSegment]]:
    """
    Fetches the transcript for a YouTube video.
    
    Tries to get manual English transcript first, falls back to auto-generated.
    
    Args:
        video_id: YouTube video ID (11 characters)
        
    Returns:
        List of TranscriptSegment objects, or None if unavailable
    """
    try:
        yt = YouTubeTranscriptApi()
        transcript_list = yt.list(video_id)
        
        # Try manual English first, then auto-generated
        try:
            transcript = transcript_list.find_transcript(['en'])
        except:
            transcript = transcript_list.find_generated_transcript(['en'])
        
        # Fetch and convert to our dataclass format
        fetched = transcript.fetch()
        
        segments = []
        for item in fetched:
            segments.append(TranscriptSegment(
                start=item.start,
                duration=getattr(item, 'duration', 0.0),
                text=item.text,
            ))
        
        return segments
        
    except Exception as e:
        print(f"Transcript Error for {video_id}: {e}")
        return None


def transcript_to_raw_data(segments: list[TranscriptSegment]) -> list[dict]:
    """
    Convert TranscriptSegment list to JSON-serializable format for DB storage.
    
    Args:
        segments: List of TranscriptSegment objects
        
    Returns:
        List of dicts with start and text keys
    """
    return [
        {"start": seg.start, "text": seg.text}
        for seg in segments
    ]


def transcript_to_full_text(segments: list[TranscriptSegment]) -> str:
    """
    Concatenate all transcript segments into a single text.
    
    Args:
        segments: List of TranscriptSegment objects
        
    Returns:
        Full transcript as a single string
    """
    return " ".join(seg.text for seg in segments)

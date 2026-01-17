"""
Fetch video metadata from YouTube Data API v3.
"""

from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from googleapiclient.discovery import build

from app.settings import get_settings


@dataclass
class VideoMetadata:
    """Container for YouTube video metadata."""
    video_id: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: Optional[datetime]
    

def get_video_metadata(video_id: str) -> Optional[VideoMetadata]:
    """
    Fetches video metadata using YouTube Data API v3.
    
    Args:
        video_id: YouTube video ID (11 characters)
        
    Returns:
        VideoMetadata object with title, description, channel info, etc.
        Returns None if video not found or API error.
    """
    settings = get_settings()
    
    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY not configured")
    
    try:
        youtube = build('youtube', 'v3', developerKey=settings.GOOGLE_API_KEY)
        
        request = youtube.videos().list(
            part="snippet",
            id=video_id
        )
        response = request.execute()
        
        if not response.get('items'):
            print(f"Video not found: {video_id}")
            return None
        
        snippet = response['items'][0]['snippet']
        
        # Parse published_at datetime
        published_at = None
        if 'publishedAt' in snippet:
            try:
                # ISO 8601 format: 2025-01-15T14:30:00Z
                published_at = datetime.fromisoformat(
                    snippet['publishedAt'].replace('Z', '+00:00')
                )
            except (ValueError, TypeError):
                pass
        
        return VideoMetadata(
            video_id=video_id,
            title=snippet.get('title', ''),
            description=snippet.get('description', ''),
            channel_id=snippet.get('channelId', ''),
            channel_title=snippet.get('channelTitle', ''),
            published_at=published_at,
        )
        
    except Exception as e:
        print(f"YouTube API Error for {video_id}: {e}")
        return None


def get_video_description(video_id: str) -> Optional[str]:
    """
    Convenience function to get just the description.
    
    Args:
        video_id: YouTube video ID
        
    Returns:
        Video description or None if not found
    """
    metadata = get_video_metadata(video_id)
    return metadata.description if metadata else None

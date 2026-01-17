"""
Playlist operations for fetching videos from YouTube playlists/channels.
"""

from typing import Optional
from googleapiclient.discovery import build

from app.settings import get_settings


def get_playlist_video_ids(playlist_id: Optional[str] = None) -> list[str]:
    """
    Get all video IDs from a YouTube playlist.
    
    Args:
        playlist_id: YouTube playlist ID. If None, uses PLAYLIST_ID from settings.
        
    Returns:
        List of video IDs in the playlist
    """
    settings = get_settings()
    
    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY not configured")
    
    playlist_id = playlist_id or settings.PLAYLIST_ID
    
    try:
        youtube = build('youtube', 'v3', developerKey=settings.GOOGLE_API_KEY)
        
        video_ids = []
        next_page_token = None
        
        while True:
            request = youtube.playlistItems().list(
                part='contentDetails',
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()
            
            for item in response.get('items', []):
                video_id = item['contentDetails']['videoId']
                video_ids.append(video_id)
            
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
        
        return video_ids
        
    except Exception as e:
        print(f"Playlist API Error: {e}")
        return []


def get_new_videos_in_playlist(
    playlist_id: Optional[str] = None,
    known_ids: Optional[set[str]] = None,
) -> list[str]:
    """
    Get video IDs from playlist that are not in the known set.
    
    Args:
        playlist_id: YouTube playlist ID. If None, uses PLAYLIST_ID from settings.
        known_ids: Set of already-known video IDs to exclude
        
    Returns:
        List of new video IDs not in known_ids
    """
    known_ids = known_ids or set()
    all_ids = get_playlist_video_ids(playlist_id)
    return [vid for vid in all_ids if vid not in known_ids]

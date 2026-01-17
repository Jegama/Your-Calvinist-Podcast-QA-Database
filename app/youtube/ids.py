"""
YouTube video ID extraction from various URL formats.
"""

import re
from typing import Optional


def get_video_id(url: str) -> str:
    """
    Extracts YouTube video ID from various URL formats.
    
    Supported formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/live/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    
    Args:
        url: YouTube video URL
        
    Returns:
        11-character video ID
        
    Raises:
        ValueError: If video ID cannot be extracted
    """
    # Pattern matches v=, /live/, /shorts/, or youtu.be/ followed by 11-char ID
    regex = r"(?:v=|\/live\/|\/shorts\/|\/youtu\.be\/|youtu\.be\/)([0-9A-Za-z_-]{11})"
    match = re.search(regex, url)
    
    if match:
        return match.group(1)
    
    # Check if it's already just a video ID
    if re.match(r"^[0-9A-Za-z_-]{11}$", url):
        return url
    
    raise ValueError(f"Could not extract video ID from: {url}")


def build_video_url(video_id: str) -> str:
    """
    Build a standard YouTube URL from a video ID.
    
    Args:
        video_id: 11-character YouTube video ID
        
    Returns:
        Full YouTube URL
    """
    return f"https://www.youtube.com/watch?v={video_id}"


def is_valid_video_id(video_id: str) -> bool:
    """
    Check if a string is a valid YouTube video ID format.
    
    Args:
        video_id: String to check
        
    Returns:
        True if valid format, False otherwise
    """
    return bool(re.match(r"^[0-9A-Za-z_-]{11}$", video_id))

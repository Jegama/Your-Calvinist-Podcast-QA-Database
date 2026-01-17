"""
Parse timestamps and questions from YouTube video descriptions.
"""

import re
from dataclasses import dataclass


@dataclass
class ParsedTimestamp:
    """A parsed timestamp with its question text."""
    time_text: str  # Original format, e.g., "1:23:45" or "23:45"
    seconds: int    # Converted to total seconds
    question: str   # The question text


def time_str_to_seconds(time_str: str) -> int:
    """
    Convert a time string to total seconds.
    
    Supports:
    - MM:SS (e.g., "23:45" -> 1425)
    - HH:MM:SS (e.g., "1:23:45" -> 5025)
    
    Args:
        time_str: Time in MM:SS or HH:MM:SS format
        
    Returns:
        Total seconds as integer
    """
    parts = list(map(int, time_str.split(':')))
    
    if len(parts) == 3:
        # HH:MM:SS
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        # MM:SS
        return parts[0] * 60 + parts[1]
    else:
        return 0


def seconds_to_time_str(seconds: int) -> str:
    """
    Convert seconds back to time string.
    
    Args:
        seconds: Total seconds
        
    Returns:
        Time string in MM:SS or HH:MM:SS format
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def parse_description_timestamps(description_text: str) -> list[ParsedTimestamp]:
    """
    Parse timestamps and questions from a video description.
    
    Handles formats:
    - "04:20 Question text" (timestamp at start)
    - "Question text 04:20" (timestamp at end)
    - "04:20 - Question text" (with separator)
    - "1:23:45 Question text" (hour format)
    
    Args:
        description_text: Full video description text
        
    Returns:
        List of ParsedTimestamp objects, sorted by time
    """
    questions = []
    
    # Pattern matches 00:00 or 1:00:00 format
    time_pattern = r"(\d{1,2}:\d{2}(?::\d{2})?)"
    
    for line in description_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Check timestamp at START of line
        match_start = re.match(f"^{time_pattern}", line)
        if match_start:
            timestamp = match_start.group(1)
            # Remove timestamp and common separators from text
            text = line[match_start.end():].strip(" -|.:")
            if text:  # Only add if there's actual question text
                questions.append(ParsedTimestamp(
                    time_text=timestamp,
                    seconds=time_str_to_seconds(timestamp),
                    question=text,
                ))
            continue
        
        # Check timestamp at END of line
        match_end = re.search(f"{time_pattern}$", line)
        if match_end:
            timestamp = match_end.group(1)
            text = line[:match_end.start()].strip(" -|.:")
            if text:
                questions.append(ParsedTimestamp(
                    time_text=timestamp,
                    seconds=time_str_to_seconds(timestamp),
                    question=text,
                ))
    
    # Sort by time
    questions.sort(key=lambda x: x.seconds)
    
    return questions

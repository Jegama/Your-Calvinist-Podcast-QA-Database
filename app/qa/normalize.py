"""
Text normalization and cleanup utilities.
"""

import re
from typing import Optional

from app.settings import get_settings


def normalize_text(text: str) -> str:
    """
    Clean up text by removing extra whitespace and normalizing.
    
    Args:
        text: Raw text to clean
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Replace multiple whitespace with single space
    text = re.sub(r'\s+', ' ', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


def generate_answer_preview(
    answer: str,
    max_length: Optional[int] = None,
) -> str:
    """
    Generate a preview of an answer for list views.
    
    Truncates at word boundary and adds ellipsis.
    
    Args:
        answer: Full answer text
        max_length: Maximum preview length (uses settings default if None)
        
    Returns:
        Truncated answer with ellipsis if needed
    """
    if not answer:
        return ""
    
    if max_length is None:
        settings = get_settings()
        max_length = settings.ANSWER_PREVIEW_LENGTH
    
    if len(answer) <= max_length:
        return answer
    
    # Find last space before max_length to avoid cutting words
    truncated = answer[:max_length]
    last_space = truncated.rfind(' ')
    
    if last_space > max_length * 0.7:  # Only use if not too short
        truncated = truncated[:last_space]
    
    return truncated.rstrip('.,;:!? ') + "..."


def clean_question_text(text: str) -> str:
    """
    Clean up question text from description.
    
    Args:
        text: Raw question text
        
    Returns:
        Cleaned question
    """
    if not text:
        return ""
    
    # Remove common prefixes like "Q:" or numbered lists
    text = re.sub(r'^(?:Q[:.]?\s*|\d+[.)]\s*)', '', text, flags=re.IGNORECASE)
    
    # Normalize whitespace
    text = normalize_text(text)
    
    # Ensure it ends with proper punctuation
    if text and text[-1] not in '.?!':
        text += '?'
    
    return text

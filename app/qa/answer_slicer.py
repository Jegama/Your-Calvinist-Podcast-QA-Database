"""
Slice transcript into answer segments based on timestamps.
"""

from dataclasses import dataclass
from typing import Optional

from app.qa.timestamp_parser import ParsedTimestamp
from app.youtube.transcripts import TranscriptSegment


@dataclass
class QAMatch:
    """A matched question with its answer from the transcript."""
    timestamp_text: str
    timestamp_seconds: int
    question: str
    answer: str
    answer_preview: str
    # Classification fields (populated after slicing)
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: Optional[list[str]] = None


def slice_answers_by_timestamps(
    questions: list[ParsedTimestamp],
    transcript: list[TranscriptSegment],
    preview_length: int = 500,
) -> list[QAMatch]:
    """
    Match questions to transcript segments based on timestamps.
    
    For each question:
    - Start time = question's timestamp
    - End time = next question's timestamp (or end of video)
    - Answer = all transcript text in that time window
    
    Args:
        questions: List of ParsedTimestamp from description
        transcript: List of TranscriptSegment from video
        preview_length: Max characters for answer_preview
        
    Returns:
        List of QAMatch objects with full answers and previews
    """
    if not questions or not transcript:
        return []
    
    results = []
    
    for i, q in enumerate(questions):
        start_time = q.seconds
        
        # End time is next question's start, or infinity for last question
        if i + 1 < len(questions):
            end_time = questions[i + 1].seconds
        else:
            # Use last transcript segment's end time
            last_seg = transcript[-1]
            end_time = last_seg.start + getattr(last_seg, 'duration', 60)
        
        # Collect transcript lines in this time window
        answer_parts = []
        for segment in transcript:
            if segment.start >= start_time and segment.start < end_time:
                answer_parts.append(segment.text)
        
        full_answer = " ".join(answer_parts)
        
        # Generate preview
        if len(full_answer) > preview_length:
            preview = full_answer[:preview_length].rsplit(' ', 1)[0] + "..."
        else:
            preview = full_answer
        
        results.append(QAMatch(
            timestamp_text=q.time_text,
            timestamp_seconds=q.seconds,
            question=q.question,
            answer=full_answer,
            answer_preview=preview,
        ))
    
    return results


def slice_answer_for_question(
    question: ParsedTimestamp,
    next_question: Optional[ParsedTimestamp],
    transcript: list[TranscriptSegment],
) -> str:
    """
    Get the answer text for a single question.
    
    Args:
        question: The current question
        next_question: The next question (or None if last)
        transcript: Full transcript segments
        
    Returns:
        Answer text from transcript
    """
    start_time = question.seconds
    
    if next_question:
        end_time = next_question.seconds
    else:
        # Use end of transcript
        if transcript:
            last_seg = transcript[-1]
            end_time = last_seg.start + getattr(last_seg, 'duration', 60)
        else:
            end_time = float('inf')
    
    answer_parts = []
    for segment in transcript:
        if segment.start >= start_time and segment.start < end_time:
            answer_parts.append(segment.text)
    
    return " ".join(answer_parts)

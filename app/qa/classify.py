"""
Classification of Q&A items using Gemini LLM.
"""

import os
import json
from typing import Optional, List
from pydantic import BaseModel, Field

from app.settings import get_settings


class Classification(BaseModel):
    """Classification result for a Q&A item."""
    category: str = Field(description="The main category from the provided list.")
    subcategory: str = Field(description="The subcategory from the provided list.")
    tags: List[str] = Field(description="A list of relevant tags or topics.")
    passages: List[str] = Field(
        default_factory=list,
        description="Bible passages explicitly cited or discussed (e.g., 'Romans 9:10-13', 'Genesis 3'). Empty list if none.",
    )


def load_categories(filepath: str = "categories.json") -> dict:
    """
    Load category definitions from JSON file.
    
    Args:
        filepath: Path to categories.json
        
    Returns:
        Dictionary of categories or empty dict if not found
    """
    if not os.path.exists(filepath):
        print(f"Warning: {filepath} not found.")
        return {}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def classify_question(
    question_text: str,
    answer_text: str,
    categories_context: Optional[dict] = None,
) -> Optional[Classification]:
    """
    Classify a Q&A pair using Gemini.
    
    Args:
        question_text: The question
        answer_text: The answer (will be truncated for API)
        categories_context: Category definitions (loaded from file if None)
        
    Returns:
        Classification object or None if failed
    """
    settings = get_settings()
    
    if not settings.GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not set, skipping classification")
        return None
    
    try:
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # Load categories if not provided
        if categories_context is None:
            categories_context = load_categories()
                
        prompt = f"""You are a theological classification assistant for the YourCalvinist Podcast Q&A database.

## CONTEXT
This is a Q&A podcast hosted by Keith Foskey, a Reformed Baptist pastor at Sovereign Grace Family Church in Jacksonville, Florida. He holds to the First London Baptist Confession (1646). The podcast features live Q&A sessions where viewers submit theological and practical questions.

## IMPORTANT NOTES ABOUT THE TRANSCRIPT
The answer text comes from auto-generated YouTube transcripts and may include:
- Sponsor ad reads (Dominion Wealth, etc.) - these are NOT part of the answer
- Live chat interactions and super chat acknowledgments - these are NOT part of the answer
- Banter between Keith and his wife Jennifer - may be conversational filler
- Gospel presentations (standard segment in each episode) - classify appropriately if relevant
- References to other content creators, debates, or church events
- Garbled book names in auto-transcripts (e.g., "first Timothy" instead of "1 Timothy", "song of Solomon" instead of "Song of Solomon") — normalize to standard book names.

Focus on the THEOLOGICAL or PRACTICAL SUBSTANCE of the answer, ignoring promotional content and casual banter.

## CATEGORIES
You MUST select category and subcategory names EXACTLY as they appear below:
{json.dumps(categories_context, indent=2)}

## YOUR TASK
Given the question and answer below, provide:

1. **category**: Select the TOP-LEVEL category that best fits (e.g., "Theology", "Practical Christian Living", "Church Practices", etc.). Use EXACT names from the list above.

2. **subcategory**: Select the most appropriate subcategory under your chosen category (e.g., "Soteriology", "Family and Relationships"). Use EXACT names from the list above.

3. **tags**: Generate 2-5 specific, searchable tags that capture the key topics discussed. These can be:
   - Specific theological terms (e.g., "penal substitutionary atonement", "infant baptism")
   - Names of theologians or figures mentioned (e.g., "John Calvin", "James White")
   - Practical topics (e.g., "sermon preparation", "church membership")
   - Do NOT include Bible passage references here — use the passages field instead.

4. **passages**: List any specific Bible passages (book + chapter, or book + chapter:verse(s)) that are explicitly cited, quoted, or substantively discussed in the answer. Use standard book names and formatting (e.g., "Romans 9:10-13", "1 John 2:15-17", "Genesis 3", "Psalm 119:105"). If no specific passages are cited, return an empty list. Do NOT include vague references like "the Bible says" — only specific citations.

## QUESTION
{question_text}

## ANSWER (from transcript, may contain extraneous content)
{answer_text}

Respond with valid JSON matching the schema. If the content is primarily sponsor material, live chat banter, or completely off-topic, use category "Non-Biblical Questions" with appropriate subcategory."""
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": Classification,
            },
        )
        
        json_text = response.text
        if not json_text:
            print("Classification returned empty response.")
            return None
        
        return Classification.model_validate_json(json_text)
        
    except Exception as e:
        print(f"Classification Error: {e}")
        return None


def classify_batch(
    items: list[dict],
    categories_context: Optional[dict] = None,
    skip_classification: bool = False,
) -> list[dict]:
    """
    Classify a batch of Q&A items.
    
    Args:
        items: List of dicts with 'question' and 'answer' keys
        categories_context: Category definitions
        skip_classification: If True, skip LLM calls entirely
        
    Returns:
        Same items with 'category', 'subcategory', and 'tags' added
    """
    if skip_classification:
        return items
    
    if categories_context is None:
        categories_context = load_categories()
    
    results = []
    for item in items:
        classification = classify_question(
            item.get('question', ''),
            item.get('answer', ''),
            categories_context,
        )
        
        if classification:
            item['category'] = classification.category
            item['subcategory'] = classification.subcategory
            item['tags'] = classification.tags
            item['passages'] = classification.passages
        else:
            item['category'] = None
            item['subcategory'] = None
            item['tags'] = []
            item['passages'] = []
        
        results.append(item)
    
    return results

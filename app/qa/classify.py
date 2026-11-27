"""
Classification of Q&A items using Gemini LLM.
"""

import json
import logging
import time
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

from app.qa.gemini import gemini_client
from app.settings import get_settings

logger = logging.getLogger(__name__)


class Classification(BaseModel):
    """Classification result for a Q&A item."""
    category: str = Field(description="The main category from the provided list.")
    subcategory: str = Field(description="The subcategory from the provided list.")
    tags: list[str] = Field(description="A list of relevant tags or topics.")
    passages: list[str] = Field(
        default_factory=list,
        description="Bible passages explicitly cited or discussed (e.g., 'Romans 9:10-13', 'Genesis 3'). Empty list if none.",
    )


def load_categories(filepath: str | Path = Path(__file__).resolve().parents[2] / "categories.json") -> dict:
    with open(filepath, encoding="utf-8") as source:
        return json.load(source)


def classification_request(
    key: str, question_text: str, answer_text: str, categories_context: dict,
) -> types.InlinedRequest:
    """Build one keyed GenerateContent request for an inline batch."""
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
    return types.InlinedRequest(
        contents=prompt,
        metadata={"key": key},
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=Classification.model_json_schema(),
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        ),
    )


# Leave headroom below the 20 MB inline request limit for the SDK envelope.
MAX_INLINE_BYTES = 16_000_000


def inline_request_size(request: types.InlinedRequest) -> int:
    return len(json.dumps(request.model_dump(mode="json", exclude_none=True))) + 512


def batch_results(job: types.BatchJob) -> dict[str, Classification | str] | None:
    """Return keyed labels or item errors, None while running, or raise for a failed job."""
    if job.state in (
        types.JobState.JOB_STATE_FAILED, types.JobState.JOB_STATE_EXPIRED,
        types.JobState.JOB_STATE_CANCELLED, types.JobState.JOB_STATE_PAUSED,
    ):
        message = job.error.message if job.error else job.state.value
        raise ValueError(f"{job.name}: {message}")
    if job.state not in (types.JobState.JOB_STATE_SUCCEEDED, types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED):
        return None

    results = {}
    entries = job.dest.inlined_responses if job.dest else None
    for entry in entries or ():
        key = (entry.metadata or {}).get("key")
        if key is None:
            continue
        if key in results:
            results[key] = "Duplicate response key"
        elif entry.error:
            results[key] = entry.error.message or "Gemini item error"
        elif entry.response and entry.response.text:
            try:
                results[key] = Classification.model_validate_json(entry.response.text)
            except ValueError as exc:
                results[key] = str(exc)[:1000]
        else:
            results[key] = "Empty classification"
    return results


def classify_batch(
    items: list[dict], categories_context: dict | None = None, skip_classification: bool = False,
) -> list[dict]:
    """Blocking in-memory API for scripts. Overnight ingestion uses the durable worker."""
    if skip_classification or not items:
        return items
    for item in items:
        item.update(category=None, subcategory=None, tags=[], passages=[])
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return items
    categories = load_categories() if categories_context is None else categories_context

    def collect(client, requests):
        name = None
        try:
            job = client.batches.create(model=settings.GEMINI_MODEL, src=requests)
            name = job.name
            logger.info("Submitted classification batch %s", name)
            deadline = time.monotonic() + 48 * 60 * 60
            while (results := batch_results(job)) is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {name}")
                time.sleep(30)
                job = client.batches.get(name=name)
        except Exception:
            logger.exception("Failed to collect classification batch %s", name)
            return
        for request in requests:
            key = request.metadata["key"]
            labels = results.get(key)
            if isinstance(labels, Classification):
                items[int(key)].update(labels.model_dump())

    with gemini_client() as client:
        requests = []
        size = 0
        for index, item in enumerate(items):
            request = classification_request(str(index), item.get("question", ""), item.get("answer", ""), categories)
            length = inline_request_size(request)
            if length > MAX_INLINE_BYTES:
                logger.warning("Item %d exceeds the inline batch limit", index)
                continue
            if requests and size + length > MAX_INLINE_BYTES:
                collect(client, requests)
                requests = []
                size = 0
            requests.append(request)
            size += length
        if requests:
            collect(client, requests)
    return items


def classify_question(
    question_text: str, answer_text: str, categories_context: dict | None = None,
) -> Classification | None:
    """Blocking one-item wrapper for callers of the original Python API."""
    item = {"question": question_text, "answer": answer_text}
    classify_batch([item], categories_context)
    if item.get("category") is None:
        return None
    return Classification.model_validate(item)

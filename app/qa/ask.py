"""Grounded answer generation for the human-facing ask endpoint."""

from __future__ import annotations

import logging
from typing import Optional

from app.settings import get_settings
from app.qa.gemini import gemini_client

logger = logging.getLogger(__name__)


async def extract_search_query(question: str) -> str:
    """Use Gemini to distill a natural-language question into concise search keywords."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return question

    try:
        prompt = (
            "Extract the core search keywords from the following question. "
            "Return ONLY the keywords separated by spaces — no explanation, "
            "no punctuation, no quotes. Remove names like 'Keith Foskey', "
            "filler words, and meta-phrases like 'what does he think about'. "
            "Keep theological terms, topic nouns, and any specific Bible references.\n\n"
            f"Question: {question}\n"
            "Keywords:"
        )
        text = await _generate_text(prompt)
        if text:
            return text
    except Exception as e:
        logger.warning("Gemini keyword extraction failed, using raw question: %s", e)

    return question


async def generate_grounded_answer(question: str, sources: list[dict]) -> Optional[str]:
    """Generate a grounded answer using only retrieved archive sources."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return None

    if not sources:
        return None

    try:
        formatted_sources = []
        for index, source in enumerate(sources, start=1):
            citation = source.get("citation") or {}
            formatted_sources.append(
                "\n".join(
                    [
                        f"SOURCE {index}",
                        f"Question ID: {source.get('id')}",
                        f"Video title: {source.get('video_title')}",
                        f"Question: {source.get('question')}",
                        f"Answer: {source.get('answer') or source.get('answer_preview')}",
                        f"Source URL: {citation.get('source_url')}",
                    ]
                )
            )

        prompt = (
            "You are answering a user's question using only Keith Foskey archive material. "
            "Use only the supplied sources. Do not add outside knowledge, do not generalize beyond the sources, "
            "and do not present an answer if the archive is insufficient. "
            "Write a concise answer in plain prose, then end with a short 'Sources:' section containing the exact source URLs used.\n\n"
            f"USER QUESTION\n{question}\n\n"
            "RETRIEVED SOURCES\n"
            + "\n\n".join(formatted_sources)
        )

        return await _generate_text(prompt) or None
    except Exception:
        logger.exception("Gemini content generation failed in /v1/ask")
        return None


async def _generate_text(prompt: str) -> str:
    async with gemini_client().aio as client:
        interaction = await client.interactions.create(
            model=get_settings().GEMINI_MODEL,
            input=prompt,
            generation_config={"thinking_level": "low"},
            store=False,
        )
        if interaction.status == "completed":
            return (interaction.output_text or "").strip()
        return ""

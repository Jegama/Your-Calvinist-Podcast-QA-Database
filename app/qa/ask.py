"""Grounded answer generation for the human-facing ask endpoint."""

from __future__ import annotations

import logging
from typing import Optional

from app.settings import get_settings

logger = logging.getLogger(__name__)


async def generate_grounded_answer(question: str, sources: list[dict]) -> Optional[str]:
    """Generate a grounded answer using only retrieved archive sources."""
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        return None

    if not sources:
        return None

    try:
        import warnings
        from google import genai
        from google.genai import types

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            client = genai.Client(api_key=settings.GEMINI_API_KEY)

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

        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.LOW
                )
            ),
        )

        text = response.text
        if not text:
            return None

        return text.strip()
    except Exception as e:
        logger.exception("Gemini content generation failed in /v1/ask")
        return None
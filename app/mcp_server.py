"""MCP server exposing Keith Foskey archive retrieval tools."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.archive import get_archive_answer, list_archive_topics, search_archive
from app.db.engine import get_session


class ArchiveCitation(BaseModel):
    question_id: str
    youtube_id: Optional[str] = None
    video_title: Optional[str] = None
    timestamp_text: Optional[str] = None
    timestamp_seconds: Optional[int] = None
    question: str
    excerpt: Optional[str] = None
    source_url: Optional[str] = None


class ArchiveSearchHit(BaseModel):
    id: str
    youtube_id: str
    video_title: Optional[str] = None
    timestamp_text: Optional[str] = None
    timestamp_seconds: int
    question: str
    answer_preview: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    rank: Optional[float] = None
    source_url: Optional[str] = None
    citation: ArchiveCitation


class ArchiveSearchResponse(BaseModel):
    query: str
    total: int
    results: list[ArchiveSearchHit]


class ArchiveAnswerDetail(BaseModel):
    id: str
    question: str
    answer: Optional[str] = None
    answer_preview: Optional[str] = None
    timestamp_text: Optional[str] = None
    timestamp_seconds: int
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    video_youtube_id: Optional[str] = None
    video_title: Optional[str] = None
    source_url: Optional[str] = None
    citation: ArchiveCitation


class ArchiveTopics(BaseModel):
    categories: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


archive_mcp = FastMCP(
    "Keith Foskey Archive",
    stateless_http=True,
    json_response=True,
    instructions=(
        "Use this server to search Keith Foskey's archived podcast Q&A. "
        "Search before answering, read the full answer for the strongest hits, "
        "and answer only from retrieved material. If the archive does not address "
        "the question, say so clearly and do not invent a position."
    ),
)


_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


# ---------------------------------------------------------------------------
# Resources – static/cacheable data clients can read without a tool call
# ---------------------------------------------------------------------------

@archive_mcp.resource(
    "keith://topics",
    name="Archive Topics",
    description="All categories, subcategories, and popular tags in the Keith Foskey archive. Read this before filtering a search.",
    mime_type="application/json",
)
def topics_resource() -> str:
    """Return the full topic taxonomy as JSON."""
    import json

    with get_session() as session:
        data = list_archive_topics(session, tag_limit=200)
    return json.dumps(data)


@archive_mcp.tool(annotations=_READ_ONLY)
def search_keith_archive(
    query: str,
    limit: int = 5,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    tags: Optional[str] = None,
    include_answers: bool = False,
) -> ArchiveSearchResponse:
    """Search Keith Foskey's archived Q&A by keyword with optional topic filters.

    Use this as the primary entry point to find what Keith has said on a topic.
    Results are ranked by relevance. Set include_answers=True to get full answer
    text inline (useful when you need content without a follow-up get_keith_answer call).
    Tags are comma-separated for AND logic, e.g. 'Calvinism,Election'.
    """
    with get_session() as session:
        result = search_archive(
            session,
            query,
            category=category,
            subcategory=subcategory,
            tags=tags,
            limit=max(1, min(limit, 10)),
            include_answers=include_answers,
        )
    return ArchiveSearchResponse.model_validate(result)


@archive_mcp.tool(annotations=_READ_ONLY)
def get_keith_answer(question_id: str) -> ArchiveAnswerDetail:
    """Fetch the full archived answer for a single question by its UUID.

    Call this after search_keith_archive to retrieve the complete answer text
    for the most relevant hits. The question_id comes from search results.
    """
    with get_session() as session:
        result = get_archive_answer(session, question_id)
    if result is None:
        raise ValueError(f"Question not found: {question_id}")
    return ArchiveAnswerDetail.model_validate(result)


@archive_mcp.tool(annotations=_READ_ONLY)
def list_keith_topics(tag_limit: int = 100) -> ArchiveTopics:
    """List available categories, subcategories, and popular tags from the archive.

    Call this to discover what topics exist before filtering a search.
    Categories and subcategories are exhaustive; tags are sorted by popularity.
    """
    with get_session() as session:
        result = list_archive_topics(session, tag_limit=max(1, min(tag_limit, 500)))
    return ArchiveTopics.model_validate(result)


@archive_mcp.prompt(title="Answer From Keith Foskey Archive")
def answer_from_keith_archive(user_question: str) -> str:
    return (
        "Answer the user's question using only Keith Foskey archive material from this MCP server. "
        "First call search_keith_archive with the user's question. Then read the full answer for the most relevant "
        "1-3 results with get_keith_answer. Synthesize only what is supported by those retrieved answers. "
        "Cite the citation.source_url for each substantive claim and preserve the linked timestamp. "
        "If the archive does not directly address the question, say that clearly.\n\n"
        f"User question: {user_question}"
    )


@archive_mcp.prompt(title="Find Keith Answer With Citations")
def find_keith_answer_with_citations(user_question: str) -> str:
    return (
        "Find the best direct answer Keith Foskey has already given in the archive. "
        "Call search_keith_archive with the user's exact question, then inspect the strongest results with get_keith_answer. "
        "Return a short answer followed by explicit citations using citation.source_url. "
        "Do not answer beyond what the retrieved material supports.\n\n"
        f"User question: {user_question}"
    )


@archive_mcp.prompt(title="Summarize Keith Position Carefully")
def summarize_keith_position_carefully(topic: str) -> str:
    return (
        "Summarize Keith Foskey's position on the requested topic using only archived Q&A material. "
        "Search broadly, inspect at least two relevant full answers when available, and distinguish between direct statements and inference. "
        "If the archive is thin or conflicting, say so explicitly. Include citations using citation.source_url.\n\n"
        f"Topic: {topic}"
    )
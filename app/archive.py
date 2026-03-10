"""Shared retrieval helpers for archive search and answer lookup."""

from __future__ import annotations

from typing import Optional, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import QAItem, Tag, QAItemTag, Video
from app.youtube.ids import build_video_url


def _parse_tags(tags: Optional[str]) -> list[str]:
    if not tags:
        return []
    return [tag.strip() for tag in tags.split(",") if tag.strip()]


def _build_source_url(youtube_id: Optional[str], timestamp_seconds: Optional[int]) -> Optional[str]:
    if not youtube_id:
        return None

    url = build_video_url(youtube_id)
    if timestamp_seconds is None:
        return url

    return f"{url}&t={timestamp_seconds}"


def _build_citation(
    *,
    question_id: str,
    youtube_id: Optional[str],
    video_title: Optional[str],
    timestamp_text: Optional[str],
    timestamp_seconds: Optional[int],
    question: str,
    excerpt: Optional[str],
) -> dict:
    return {
        "question_id": question_id,
        "youtube_id": youtube_id,
        "video_title": video_title,
        "timestamp_text": timestamp_text,
        "timestamp_seconds": timestamp_seconds,
        "question": question,
        "excerpt": excerpt,
        "source_url": _build_source_url(youtube_id, timestamp_seconds),
    }


def search_archive(
    session: Session,
    query: str,
    *,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = 5,
    offset: int = 0,
    include_answers: bool = False,
) -> dict:
    normalized_query = query.strip()
    if not normalized_query:
        return {"query": query, "total": 0, "results": []}

    tag_list = _parse_tags(tags)
    answer_select = ",\n            q.answer" if include_answers else ""

    base_sql = f"""
        SELECT
            q.id,
            q.timestamp_text,
            q.timestamp_seconds,
            q.question,
            q.answer_preview,
            q.category,
            q.subcategory,
            v.youtube_id,
            v.published_at,
            v.title AS video_title,
            ts_rank(q.search_tsv, plainto_tsquery('english', :query)) AS rank,
            ARRAY_AGG(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) AS tags
            {answer_select}
        FROM qa_items q
        JOIN videos v ON v.id = q.video_id
        LEFT JOIN qa_item_tags qt ON qt.qa_item_id = q.id
        LEFT JOIN tags t ON t.id = qt.tag_id
        WHERE v.status = 'processed'
          AND q.search_tsv @@ plainto_tsquery('english', :query)
    """

    params: dict[str, object] = {
        "query": normalized_query,
        "limit": limit,
        "offset": offset,
    }

    if category:
        base_sql += " AND q.category = :category"
        params["category"] = category

    if subcategory:
        base_sql += " AND q.subcategory = :subcategory"
        params["subcategory"] = subcategory

    for index, tag_name in enumerate(tag_list):
        param_name = f"tag_{index}"
        base_sql += (
            f" AND EXISTS ("
            f"SELECT 1 FROM qa_item_tags qt{index} "
            f"JOIN tags t{index} ON t{index}.id = qt{index}.tag_id "
            f"WHERE qt{index}.qa_item_id = q.id AND t{index}.name = :{param_name}"
            f")"
        )
        params[param_name] = tag_name

    base_sql += """
        GROUP BY q.id, v.youtube_id, v.title, v.published_at
        ORDER BY rank DESC, v.published_at DESC, q.timestamp_seconds
        LIMIT :limit OFFSET :offset
    """

    count_sql = """
        SELECT COUNT(DISTINCT q.id)
        FROM qa_items q
        JOIN videos v ON v.id = q.video_id
        WHERE v.status = 'processed'
          AND q.search_tsv @@ plainto_tsquery('english', :query)
    """

    count_params: dict[str, object] = {"query": normalized_query}

    if category:
        count_sql += " AND q.category = :category"
        count_params["category"] = category

    if subcategory:
        count_sql += " AND q.subcategory = :subcategory"
        count_params["subcategory"] = subcategory

    for index, tag_name in enumerate(tag_list):
        param_name = f"tag_{index}"
        count_sql += (
            f" AND EXISTS ("
            f"SELECT 1 FROM qa_item_tags qt{index} "
            f"JOIN tags t{index} ON t{index}.id = qt{index}.tag_id "
            f"WHERE qt{index}.qa_item_id = q.id AND t{index}.name = :{param_name}"
            f")"
        )
        count_params[param_name] = tag_name

    rows = session.execute(text(base_sql), params)
    total = session.execute(text(count_sql), count_params).scalar() or 0

    results = []
    for row in rows:
        citation = _build_citation(
            question_id=str(row.id),
            youtube_id=row.youtube_id,
            video_title=row.video_title,
            timestamp_text=row.timestamp_text,
            timestamp_seconds=row.timestamp_seconds,
            question=row.question,
            excerpt=row.answer_preview,
        )
        result = {
            "id": str(row.id),
            "youtube_id": row.youtube_id,
            "video_title": row.video_title,
            "timestamp_text": row.timestamp_text,
            "timestamp_seconds": row.timestamp_seconds,
            "question": row.question,
            "answer_preview": row.answer_preview,
            "category": row.category,
            "subcategory": row.subcategory,
            "tags": row.tags or [],
            "rank": float(row.rank) if row.rank is not None else None,
            "source_url": citation["source_url"],
            "citation": citation,
        }
        if include_answers:
            result["answer"] = row.answer
        results.append(result)

    return {
        "query": normalized_query,
        "total": total,
        "results": results,
    }


def get_archive_answer(session: Session, question_id: str) -> Optional[dict]:
    try:
        parsed_question_id = UUID(question_id)
    except ValueError:
        return None

    qa_item = (
        session.query(QAItem)
        .join(Video)
        .filter(QAItem.id == parsed_question_id)
        .filter(Video.status == "processed")
        .first()
    )
    if not qa_item:
        return None

    video = qa_item.video
    timestamp_seconds = cast(int, qa_item.timestamp_seconds)
    timestamp_text = cast(Optional[str], qa_item.timestamp_text)
    question = cast(str, qa_item.question)
    answer_preview = cast(Optional[str], qa_item.answer_preview)
    question_id = str(qa_item.id)
    citation = _build_citation(
        question_id=question_id,
        youtube_id=video.youtube_id if video else None,
        video_title=video.title if video else None,
        timestamp_text=timestamp_text,
        timestamp_seconds=timestamp_seconds,
        question=question,
        excerpt=answer_preview,
    )
    return {
        "id": question_id,
        "question": question,
        "answer": qa_item.answer,
        "answer_preview": answer_preview,
        "timestamp_text": timestamp_text,
        "timestamp_seconds": timestamp_seconds,
        "category": qa_item.category,
        "subcategory": qa_item.subcategory,
        "tags": [tag.name for tag in qa_item.tags],
        "video_youtube_id": video.youtube_id if video else None,
        "video_title": video.title if video else None,
        "source_url": citation["source_url"],
        "citation": citation,
    }


def list_archive_topics(session: Session, tag_limit: int = 100) -> dict:
    categories = session.query(QAItem.category).filter(QAItem.category.isnot(None)).distinct().all()
    subcategories = session.query(QAItem.subcategory).filter(QAItem.subcategory.isnot(None)).distinct().all()
    tags = (
        session.query(Tag.name)
        .join(QAItemTag, Tag.id == QAItemTag.tag_id)
        .group_by(Tag.id)
        .order_by(text("COUNT(qa_item_tags.qa_item_id) DESC"))
        .limit(tag_limit)
        .all()
    )

    return {
        "categories": sorted(row[0] for row in categories),
        "subcategories": sorted(row[0] for row in subcategories),
        "tags": [row[0] for row in tags],
    }
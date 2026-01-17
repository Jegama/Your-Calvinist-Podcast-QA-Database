"""
Public read-only API endpoints for the website.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.dependencies import get_db
from app.db.models import Video, QAItem, Tag, QAItemTag
from app.schemas import (
    VideoOut,
    VideoDetailOut,
    VideoSummaryOut,
    QAItemOut,
    QAItemDetailOut,
    SearchResult,
    SearchResponse,
)

router = APIRouter(prefix="/v1", tags=["public"])


# --- Video Endpoints ---

@router.get("/videos", response_model=list[VideoOut])
def list_videos(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None, description="Search in video titles"),
    db: Session = Depends(get_db),
):
    """
    List all processed videos.
    
    - **limit**: Max number of results (1-100)
    - **offset**: Pagination offset
    - **q**: Optional title search
    """
    query = db.query(Video).filter(Video.status == "processed")
    
    if q:
        query = query.filter(Video.title.ilike(f"%{q}%"))
    
    query = query.order_by(Video.published_at.desc())
    videos = query.offset(offset).limit(limit).all()
    
    return videos


@router.get("/videos/summary", response_model=list[VideoSummaryOut])
def list_videos_summary(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    List videos with aggregated Q&A metadata.
    
    Returns categories, subcategories, and tags for each video.
    Useful for frontend filtering/faceting.
    """
    # Raw SQL for complex aggregation
    sql = text("""
        SELECT 
            v.youtube_id,
            v.title,
            v.channel_title,
            v.published_at,
            COUNT(q.id) AS qa_count,
            ARRAY_AGG(DISTINCT q.category) FILTER (WHERE q.category IS NOT NULL) AS categories,
            ARRAY_AGG(DISTINCT q.subcategory) FILTER (WHERE q.subcategory IS NOT NULL) AS subcategories,
            ARRAY_AGG(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) AS tags
        FROM videos v
        LEFT JOIN qa_items q ON q.video_id = v.id
        LEFT JOIN qa_item_tags qt ON qt.qa_item_id = q.id
        LEFT JOIN tags t ON t.id = qt.tag_id
        WHERE v.status = 'processed'
        GROUP BY v.id
        ORDER BY v.published_at DESC
        LIMIT :limit OFFSET :offset
    """)
    
    result = db.execute(sql, {"limit": limit, "offset": offset})
    
    summaries = []
    for row in result:
        summaries.append(VideoSummaryOut(
            youtube_id=row.youtube_id,
            title=row.title,
            channel_title=row.channel_title,
            published_at=row.published_at,
            qa_count=row.qa_count or 0,
            categories=row.categories or [],
            subcategories=row.subcategories or [],
            tags=row.tags or [],
        ))
    
    return summaries


@router.get("/videos/{youtube_id}", response_model=VideoDetailOut)
def get_video(
    youtube_id: str,
    db: Session = Depends(get_db),
):
    """
    Get a single video by YouTube ID.
    """
    video = db.query(Video).filter(Video.youtube_id == youtube_id).first()
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found: {youtube_id}"
        )
    
    return video


@router.get("/videos/{youtube_id}/questions", response_model=list[QAItemOut])
def get_video_questions(
    youtube_id: str,
    category: Optional[str] = Query(default=None),
    subcategory: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Keyword search in question/answer"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Get all Q&A items for a specific video.
    
    - **category**: Filter by category
    - **subcategory**: Filter by subcategory
    - **tag**: Filter by tag name
    - **q**: Keyword search using full-text search
    """
    # Get video first
    video = db.query(Video).filter(Video.youtube_id == youtube_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found: {youtube_id}"
        )
    
    query = db.query(QAItem).filter(QAItem.video_id == video.id)
    
    # Apply filters
    if category:
        query = query.filter(QAItem.category == category)
    
    if subcategory:
        query = query.filter(QAItem.subcategory == subcategory)
    
    if tag:
        query = query.join(QAItem.tags).filter(Tag.name == tag)
    
    if q:
        # Use full-text search
        query = query.filter(
            QAItem.search_tsv.op("@@")(func.plainto_tsquery("english", q))
        )
    
    query = query.order_by(QAItem.timestamp_seconds)
    qa_items = query.offset(offset).limit(limit).all()
    
    # Convert to response model with tags
    results = []
    for item in qa_items:
        results.append(QAItemOut(
            id=str(getattr(item, 'id')),
            timestamp_text=getattr(item, 'timestamp_text'),
            timestamp_seconds=getattr(item, 'timestamp_seconds'),
            question=getattr(item, 'question'),
            answer_preview=getattr(item, 'answer_preview'),
            category=getattr(item, 'category'),
            subcategory=getattr(item, 'subcategory'),
            tags=[getattr(t, 'name') for t in item.tags],
        ))
    
    return results


# --- Q&A / Search Endpoints ---

@router.get("/questions/search", response_model=SearchResponse)
def search_questions(
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(default=None),
    subcategory: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Search across all Q&A items using full-text search.
    
    - **q**: Search query (required, min 2 chars)
    - **category**: Filter by category
    - **subcategory**: Filter by subcategory  
    - **tag**: Filter by tag name
    """
    # Build the search query using raw SQL for ranking
    base_sql = """
        SELECT 
            q.id,
            q.timestamp_text,
            q.timestamp_seconds,
            q.question,
            q.answer_preview,
            q.category,
            q.subcategory,
            v.youtube_id,
            v.title as video_title,
            ts_rank(q.search_tsv, plainto_tsquery('english', :query)) as rank,
            ARRAY_AGG(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL) as tags
        FROM qa_items q
        JOIN videos v ON v.id = q.video_id
        LEFT JOIN qa_item_tags qt ON qt.qa_item_id = q.id
        LEFT JOIN tags t ON t.id = qt.tag_id
        WHERE v.status = 'processed'
          AND q.search_tsv @@ plainto_tsquery('english', :query)
    """
    
    params = {"query": q, "limit": limit, "offset": offset}
    
    # Add filters
    if category:
        base_sql += " AND q.category = :category"
        params["category"] = category
    
    if subcategory:
        base_sql += " AND q.subcategory = :subcategory"
        params["subcategory"] = subcategory
    
    if tag:
        base_sql += " AND EXISTS (SELECT 1 FROM qa_item_tags qt2 JOIN tags t2 ON t2.id = qt2.tag_id WHERE qt2.qa_item_id = q.id AND t2.name = :tag)"
        params["tag"] = tag
    
    base_sql += """
        GROUP BY q.id, v.youtube_id, v.title
        ORDER BY rank DESC
        LIMIT :limit OFFSET :offset
    """
    
    result = db.execute(text(base_sql), params)
    
    # Count total results
    count_sql = """
        SELECT COUNT(DISTINCT q.id)
        FROM qa_items q
        JOIN videos v ON v.id = q.video_id
        WHERE v.status = 'processed'
          AND q.search_tsv @@ plainto_tsquery('english', :query)
    """
    count_params = {"query": q}
    
    if category:
        count_sql += " AND q.category = :category"
        count_params["category"] = category
    if subcategory:
        count_sql += " AND q.subcategory = :subcategory"
        count_params["subcategory"] = subcategory
    if tag:
        count_sql += " AND EXISTS (SELECT 1 FROM qa_item_tags qt2 JOIN tags t2 ON t2.id = qt2.tag_id WHERE qt2.qa_item_id = q.id AND t2.name = :tag)"
        count_params["tag"] = tag
    
    total = db.execute(text(count_sql), count_params).scalar() or 0
    
    # Build results
    results = []
    for row in result:
        results.append(SearchResult(
            id=str(row.id),
            youtube_id=row.youtube_id,
            video_title=row.video_title,
            timestamp_text=row.timestamp_text,
            timestamp_seconds=row.timestamp_seconds,
            question=row.question,
            answer_preview=row.answer_preview,
            category=row.category,
            subcategory=row.subcategory,
            tags=row.tags or [],
            rank=row.rank,
        ))
    
    return SearchResponse(
        query=q,
        total=total,
        results=results,
    )


@router.get("/questions/{question_id}", response_model=QAItemDetailOut)
def get_question(
    question_id: str,
    db: Session = Depends(get_db),
):
    """
    Get a single Q&A item by ID with full answer.
    """
    qa_item = db.query(QAItem).filter(QAItem.id == question_id).first()
    
    if not qa_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question not found: {question_id}"
        )
    
    # Get video info
    video = db.query(Video).filter(Video.id == qa_item.video_id).first()
    
    return QAItemDetailOut(
        id=str(getattr(qa_item, 'id')),
        timestamp_text=getattr(qa_item, 'timestamp_text'),
        timestamp_seconds=getattr(qa_item, 'timestamp_seconds'),
        question=getattr(qa_item, 'question'),
        answer=getattr(qa_item, 'answer'),
        answer_preview=getattr(qa_item, 'answer_preview'),
        category=getattr(qa_item, 'category'),
        subcategory=getattr(qa_item, 'subcategory'),
        tags=[getattr(t, 'name') for t in qa_item.tags],
        video_youtube_id=getattr(video, 'youtube_id') if video else None,
        video_title=getattr(video, 'title') if video else None,
    )


# --- Metadata Endpoints ---

@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)):
    """
    Get all unique categories.
    """
    result = db.query(QAItem.category).filter(
        QAItem.category.isnot(None)
    ).distinct().all()
    
    return sorted([r[0] for r in result])


@router.get("/subcategories", response_model=list[str])
def list_subcategories(
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Get all unique subcategories, optionally filtered by category.
    """
    query = db.query(QAItem.subcategory).filter(QAItem.subcategory.isnot(None))
    
    if category:
        query = query.filter(QAItem.category == category)
    
    result = query.distinct().all()
    
    return sorted([r[0] for r in result])


@router.get("/tags", response_model=list[str])
def list_tags(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Get all tags, ordered by usage count.
    """
    result = db.query(
        Tag.name,
        func.count(QAItemTag.qa_item_id).label("count")
    ).join(
        QAItemTag, Tag.id == QAItemTag.tag_id
    ).group_by(
        Tag.id
    ).order_by(
        func.count(QAItemTag.qa_item_id).desc()
    ).limit(limit).all()
    
    return [r[0] for r in result]

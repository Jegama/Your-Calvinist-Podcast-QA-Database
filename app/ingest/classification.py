"""Submit and collect asynchronous Gemini classification jobs."""

from datetime import datetime, timedelta, timezone

from google.genai import errors
from sqlalchemy import select

from app.db import crud
from app.db.engine import get_session
from app.db.models import ClassificationBatch, QAItem
from app.qa.classify import MAX_INLINE_BYTES, batch_results, classification_request, inline_request_size, load_categories
from app.qa.gemini import gemini_client
from app.settings import get_settings

CHECK_INTERVAL = timedelta(minutes=5)
MAX_ITEMS = 100


def _claim_requests():
    with get_session() as db:
        rows = db.scalars(
            select(QAItem).where(QAItem.classification_state == "queued")
            .order_by(QAItem.created_at, QAItem.id).limit(MAX_ITEMS)
            .with_for_update(skip_locked=True)
        ).all()
        if not rows:
            return None, []

        categories = load_categories()
        requests = []
        batch = ClassificationBatch(next_check=datetime.now(timezone.utc) + CHECK_INTERVAL)
        size = 0
        for row in rows:
            req = classification_request(str(row.id), row.question, row.answer or "", categories)
            length = inline_request_size(req)
            if length > MAX_INLINE_BYTES:
                row.classification_state = "failed"
                row.classification_error = "Question exceeds the inline batch size limit"
                continue
            if size + length > MAX_INLINE_BYTES:
                break
            if not requests:
                db.add(batch)
                db.flush()
            row.classification_batch_id = batch.id
            row.classification_state = "batched"
            requests.append(req)
            size += length
        return batch.id, requests


def _record_name(batch_id, name):
    if not name:
        raise ValueError("Google returned a batch without a resource name")
    with get_session() as db:
        batch = db.get(ClassificationBatch, batch_id, with_for_update=True)
        if batch:
            batch.remote_name = name


def _finish(batch_id, results=None, error=None):
    # A re-ingest with changed text detaches that row from the old batch.
    results = results or {}
    counts = {"classified": 0, "failed": 0}
    with get_session() as db:
        batch = db.get(ClassificationBatch, batch_id, with_for_update=True)
        if not batch:
            return counts
        rows = db.scalars(
            select(QAItem).where(QAItem.classification_batch_id == batch_id)
            .order_by(QAItem.video_id, QAItem.timestamp_seconds).with_for_update()
        ).all()
        for row in rows:
            labels = error or results.get(str(row.id), "Missing response key")
            if isinstance(labels, str):
                row.classification_error = labels[:1000]
                row.classification_state = "failed"
                counts["failed"] += 1
            else:
                row.category = labels.category
                row.subcategory = labels.subcategory
                row.passages = labels.passages
                row.tags = crud.get_or_create_tags(db, list(dict.fromkeys(labels.tags)))
                row.classification_error = None
                row.classification_state = "done"
                counts["classified"] += 1
            row.classification_batch_id = None
        db.flush()
        db.delete(batch)
    return counts


def _poll_one(client):
    now = datetime.now(timezone.utc)
    with get_session() as db:
        batch = db.scalar(
            select(ClassificationBatch).where(ClassificationBatch.next_check <= now)
            .order_by(ClassificationBatch.next_check).limit(1).with_for_update(skip_locked=True)
        )
        if not batch:
            return {}
        batch.next_check = now + CHECK_INTERVAL
        batch_id, name = batch.id, batch.remote_name
        created = batch.created_at
        cursor = batch.recovery_cursor

    if not name:
        # A crash or timeout may have lost the create acknowledgement. Look up
        # one page per invocation. Never send a second create for this claim.
        page = client.batches.list(config={"page_size": 100, "page_token": cursor})
        match = next((job for job in page.page if job.display_name == f"qa-{batch_id}"), None)
        if not match:
            next_page = page.config.get("page_token")
            if not next_page and now - created > timedelta(hours=24):
                return _finish(batch_id, error=f"Unconfirmed submission qa-{batch_id}. Check Google before retrying.")
            with get_session() as db:
                batch = db.get(ClassificationBatch, batch_id)
                if batch:
                    batch.recovery_cursor = next_page
            return {"reconciling": 1}
        _record_name(batch_id, match.name)
        return {"recovered": 1}

    try:
        job = client.batches.get(name=name)
    except errors.ClientError as exc:
        if exc.code == 404:
            return _finish(batch_id, error=f"Gemini batch {name} was not found")
        raise
    try:
        results = batch_results(job)
    except ValueError as exc:
        return _finish(batch_id, error=str(exc))
    if results is None:
        return {"running": 1}
    return _finish(batch_id, results)


def run_classification_worker(*, collect_only: bool = False) -> dict:
    """Advance one batch with at most one Gemini API call per invocation."""
    if not get_settings().GEMINI_API_KEY:
        return {"disabled": True}
    with gemini_client() as client:
        if collect_only:
            return _poll_one(client)
        batch_id, requests = _claim_requests()
        if not requests:
            return _poll_one(client)
        try:
            job = client.batches.create(
                model=get_settings().GEMINI_MODEL,
                src=requests,
                config={"display_name": f"qa-{batch_id}"},
            )
        except errors.ClientError as exc:
            if exc.code == 408:
                raise  # Ambiguous acknowledgement. Recover by display name.
            return _finish(batch_id, error=f"Batch rejected ({exc.code}): {exc.message}")
        _record_name(batch_id, job.name)
        return {"submitted": len(requests), "batch": job.name}

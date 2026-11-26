"""Run against PostgreSQL with TEST_DATABASE_URL. Each test owns a temporary schema."""

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from google.genai import types
from sqlalchemy import create_engine, make_url, select, text, update
from sqlalchemy.orm import sessionmaker

from app.settings import get_settings


def response(key, category="Theology"):
    labels = json.dumps({"category": category, "subcategory": "Prayer", "tags": ["prayer"], "passages": []})
    return types.InlinedResponse(metadata={"key": str(key)}, response={
        "candidates": [{"content": {"parts": [{"text": labels}]}}]
    })


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Set TEST_DATABASE_URL to run PostgreSQL regressions")
class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(get_settings(), "DATABASE_URL", os.environ["TEST_DATABASE_URL"]))
        from app.db import engine
        from app.db.models import Base, Video

        url = make_url(os.environ["TEST_DATABASE_URL"])
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg2")
        schema = "test_qa_" + uuid4().hex
        admin = create_engine(url)
        self.addCleanup(admin.dispose)
        with admin.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA {schema}")

        def drop_test_schema():
            with admin.begin() as conn:
                conn.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")

        self.addCleanup(drop_test_schema)
        self.engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, autoflush=False)
        self.enterContext(patch.object(engine, "SessionLocal", self.sessions))
        self.enterContext(patch.object(get_settings(), "GEMINI_API_KEY", "local-test"))
        with self.sessions.begin() as db:
            video = Video(youtube_id="testvideo01", url="https://example.org/test", status="processed")
            db.add(video)
            db.flush()
            self.video_id = video.id

        self.client = MagicMock()
        self.client.batches.create.return_value = types.BatchJob(name="batches/test")
        context = self.enterContext(patch("app.ingest.classification.gemini_client"))
        context.return_value.__enter__.return_value = self.client

    def question(self, seconds, answer="test", **kwargs):
        from app.db.crud import upsert_qa_item
        with self.sessions.begin() as db:
            qa = upsert_qa_item(db, self.video_id, f"0:{seconds:02d}", seconds, f"Q {seconds}",
                                answer, queue_classification=True, **kwargs)
            return qa.id

    def make_due(self):
        from app.db.models import ClassificationBatch
        with self.sessions.begin() as db:
            db.execute(update(ClassificationBatch).values(next_check=datetime.now(timezone.utc)))

    def test_partial_and_out_of_order_results(self):
        from app.db.models import QAItem
        from app.ingest.classification import run_classification_worker
        keys = [self.question(i) for i in range(5)]
        self.assertEqual(run_classification_worker()["submitted"], 5)
        src = self.client.batches.create.call_args.kwargs["src"]
        self.assertEqual({r.metadata["key"] for r in src}, set(map(str, keys)))
        self.assertTrue(all(r.config.response_json_schema for r in src))
        self.make_due()
        self.client.batches.get.return_value = types.BatchJob(
            state="JOB_STATE_PARTIALLY_SUCCEEDED",
            dest={"inlined_responses": [
                response(keys[3], "Fourth"), response(keys[0], "First"),
                types.InlinedResponse(metadata={"key": str(keys[1])}, error={"message": "blocked"}),
                response(keys[4]), response(keys[4]),
            ]},
        )
        self.assertEqual(run_classification_worker(), {"classified": 2, "failed": 3})
        with self.sessions() as db:
            rows = db.scalars(select(QAItem).order_by(QAItem.timestamp_seconds)).all()
            self.assertEqual([r.category for r in rows], ["First", None, None, "Fourth", None])
            self.assertEqual([t.name for t in rows[0].tags], ["prayer"])
            self.assertEqual(rows[1].classification_error, "blocked")
            self.assertEqual(rows[2].classification_state, "failed")
            self.assertEqual(rows[4].classification_state, "failed")
        self.assertFalse(run_classification_worker())
        self.client.batches.create.assert_called_once()

    def test_reingest_cannot_apply_stale_answers_or_duplicate_active_work(self):
        from app.db.models import QAItem
        from app.ingest.classification import run_classification_worker
        first, second = self.question(0), self.question(5)
        run_classification_worker()
        self.question(0)
        self.assertEqual(run_classification_worker(), {})
        self.question(5, "New answer")
        self.make_due()
        self.client.batches.get.return_value = types.BatchJob(
            state="JOB_STATE_SUCCEEDED", dest={"inlined_responses": [response(first), response(second)]})
        self.assertEqual(run_classification_worker(collect_only=True), {"classified": 1, "failed": 0})
        with self.sessions() as db:
            self.assertEqual(db.get(QAItem, second).classification_state, "queued")
            self.assertIsNone(db.get(QAItem, second).category)
        self.question(0)
        with self.sessions() as db:
            self.assertEqual(db.get(QAItem, first).category, "Theology")
        self.client.batches.create.assert_called_once()

    def test_lost_create_acknowledgement_recovers_by_display_name(self):
        from app.db.models import ClassificationBatch
        from app.ingest.classification import run_classification_worker
        key = self.question(0)
        self.client.batches.create.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            run_classification_worker()
        with self.sessions() as db:
            batch_id = db.scalar(select(ClassificationBatch.id))
        self.client.batches.list.side_effect = [
            SimpleNamespace(page=[], config={"page_token": "page2"}),
            SimpleNamespace(page=[types.BatchJob(name="batches/found", display_name=f"qa-{batch_id}")]),
        ]
        self.make_due()
        self.assertEqual(run_classification_worker(), {"reconciling": 1})
        self.make_due()
        self.client.batches.get.return_value = types.BatchJob(
            state="JOB_STATE_SUCCEEDED", dest={"inlined_responses": [response(key)]})
        self.assertEqual(run_classification_worker(), {"recovered": 1})
        self.client.batches.get.assert_not_called()
        self.make_due()
        self.assertEqual(run_classification_worker(), {"classified": 1, "failed": 0})
        self.client.batches.get.assert_called_once_with(name="batches/found")
        self.assertEqual(self.client.batches.list.call_args.kwargs["config"]["page_token"], "page2")
        self.client.batches.create.assert_called_once()

    def test_submission_and_collection_use_separate_provider_calls(self):
        from app.ingest.classification import run_classification_worker
        self.question(1)
        run_classification_worker()
        self.make_due()
        self.question(2)
        self.client.batches.reset_mock()
        self.client.batches.get.return_value = types.BatchJob(state="JOB_STATE_RUNNING")

        self.assertEqual(run_classification_worker()["submitted"], 1)
        self.client.batches.get.assert_not_called()
        self.assertEqual(run_classification_worker(collect_only=True), {"running": 1})
        self.client.batches.create.assert_called_once()
        self.client.batches.get.assert_called_once()

    def wait_for_blocked_collector(self, holder, collector):
        deadline = monotonic() + 5
        while not holder.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE NOT granted "
            "AND pg_backend_pid() = ANY(pg_blocking_pids(pid)))"
        )):
            if collector.done():
                collector.result()
            self.assertLess(monotonic(), deadline, "collector never waited on the other transaction")
            sleep(0.02)

    def test_collectors_acquire_shared_tags_in_one_order_across_questions(self):
        from app.db import crud
        from app.db.models import QAItem
        from app.ingest.classification import _claim_requests, _finish
        from app.qa.classify import Classification
        first, second = self.question(0), self.question(5)
        batch, _ = _claim_requests()
        results = {
            str(first): Classification(category="C", subcategory="S", tags=["zulu"]),
            str(second): Classification(category="C", subcategory="S", tags=["alpha", "zulu", "alpha"]),
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.sessions.begin() as holder:
                holder.execute(text("SET LOCAL lock_timeout = '500ms'"))
                crud.get_or_create_tags(holder, ["alpha"])
                collector = pool.submit(_finish, batch, results)
                self.wait_for_blocked_collector(holder, collector)
                # The blocked collector must not have inserted zulu for its first question.
                crud.get_or_create_tags(holder, ["zulu"])
            self.assertEqual(collector.result(timeout=5), {"classified": 2, "failed": 0})
        with self.sessions() as db:
            self.assertEqual([t.name for t in db.get(QAItem, first).tags], ["zulu"])
            self.assertCountEqual([t.name for t in db.get(QAItem, second).tags], ["alpha", "zulu"])

    def test_collector_waits_on_first_timestamp_before_locking_second(self):
        from app.db.models import QAItem
        from app.ingest.classification import _claim_requests, _finish
        # Force UUID order to be the opposite of ingestion order.
        first, second = UUID(int=2), UUID(int=1)
        for seconds, new_id in ((0, first), (5, second)):
            old_id = self.question(seconds)
            with self.sessions.begin() as db:
                db.execute(update(QAItem).where(QAItem.id == old_id).values(id=new_id))
        batch, _ = _claim_requests()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.sessions.begin() as ingest:
                ingest.get(QAItem, first, with_for_update=True)
                collector = pool.submit(_finish, batch, error="test")
                self.wait_for_blocked_collector(ingest, collector)
                # With the old order the collector already owns this row.
                ingest.get(QAItem, second, with_for_update={"nowait": True})
            self.assertEqual(collector.result(timeout=5)["failed"], 2)

    def test_stored_fresh_and_manual_ingestion(self):
        from app.cli import ingest_manual_timestamps as manual
        from app.db.models import QAItem
        from app.ingest import pipeline
        from app.youtube.metadata import VideoMetadata
        from app.youtube.transcripts import TranscriptSegment
        description = "Questions and Timestamps:\n0:01 What is prayer?"
        metadata = VideoMetadata("testvideo01", "Test", description, "id", "Test", None)
        for module in (manual, pipeline):
            self.enterContext(patch.object(module, "get_video_metadata", return_value=metadata))
            self.enterContext(patch.object(module, "get_raw_transcript", return_value=[TranscriptSegment(1, 5, "Prayer")]))
        self.assertEqual(pipeline.process_video("testvideo01", verbose=False).questions_saved, 1)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(QAItem.classification_state)), "queued")
        self.assertTrue(pipeline.reprocess_from_stored_transcript("testvideo01", skip_classification=True, verbose=False).success)
        self.assertTrue(manual.process_video_with_manual_timestamps("testvideo01", description, dry_run=True, verbose=False)["success"])
        with self.sessions() as db:
            self.assertIsNone(db.scalar(select(QAItem.classification_state)))
        self.assertTrue(manual.process_video_with_manual_timestamps("testvideo01", description, verbose=False)["success"])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(QAItem.classification_state)), "queued")
        self.client.batches.create.assert_not_called()

    def test_migration_on_existing_rows(self):
        migration = Path(__file__).resolve().parents[1] / "migrations/002_classification_batches.sql"
        with self.engine.begin() as con:
            con.exec_driver_sql("ALTER TABLE qa_items DROP COLUMN classification_batch_id, "
                                "DROP COLUMN classification_state, DROP COLUMN classification_error")
            con.exec_driver_sql("DROP TABLE classification_batches")
            con.exec_driver_sql("INSERT INTO qa_items (id,video_id,question,timestamp_seconds,category) "
                                "VALUES (%s,%s,'Existing',0,'Theology')", (uuid4(), self.video_id))
        for _ in range(2):
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as con:
                con.exec_driver_sql(migration.read_text())
        with self.engine.connect() as con:
            self.assertEqual(con.exec_driver_sql("SELECT category, classification_state FROM qa_items").one(),
                             ("Theology", None))

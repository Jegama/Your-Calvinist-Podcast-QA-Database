import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.qa.ask import extract_search_query, generate_grounded_answer
from app.settings import get_settings


class APICompatibilityTests(unittest.TestCase):
    def test_mcp_advertises_the_archive_tools_and_resource(self):
        # The listing exercises the ASGI lifespan and transport without opening a DB connection.
        with patch.object(get_settings(), "DATABASE_URL", "postgresql://localhost/unused"):
            from app.main import app
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            self.assertIn("/v1/ask", client.get("/openapi.json").json()["paths"])
            headers = {"Accept": "application/json, text/event-stream"}

            def rpc(method):
                request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}
                result = client.post("/mcp/", json=request, headers=headers)
                self.assertEqual(result.status_code, 200)
                return result.json()["result"]

            tools = rpc("tools/list")["tools"]
            self.assertEqual({t["name"] for t in tools}, {"get_keith_answer", "list_keith_topics", "search_keith_archive"})
            self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in tools))
            self.assertIn("keith://topics", {r["uri"] for r in rpc("resources/list")["resources"]})
            self.assertIn("answer_from_keith_archive", {p["name"] for p in rpc("prompts/list")["prompts"]})

    def test_interactive_calls_and_fallbacks(self):
        with patch.object(get_settings(), "GEMINI_API_KEY", "test"), patch("app.qa.ask.gemini_client") as factory:
            api = factory.return_value.aio.__aenter__.return_value
            api.interactions.create = AsyncMock(side_effect=[
                SimpleNamespace(status="completed", output_text=" prayer "),
                SimpleNamespace(status="completed", output_text="Answer with a citation."),
                SimpleNamespace(status="incomplete", output_text="Partial"),
            ])
            self.assertEqual(asyncio.run(extract_search_query("What is prayer?")), "prayer")
            source = {"question": "What is prayer?", "answer": "Speaking to God.", "citation": {"source_url": "https://example.org/test"}}
            self.assertEqual(asyncio.run(generate_grounded_answer("What is prayer?", [source])), "Answer with a citation.")
            self.assertEqual(asyncio.run(extract_search_query("Raw question")), "Raw question")
            args = api.interactions.create.await_args_list[1].kwargs
            self.assertIn(source["citation"]["source_url"], args["input"])
            self.assertEqual(args["model"], get_settings().GEMINI_MODEL)
            self.assertFalse(args["store"])

    def test_in_memory_classification_uses_a_real_batch_request(self):
        from google.genai import types
        from app.qa.classify import classify_batch
        items = [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]
        with patch.object(get_settings(), "GEMINI_API_KEY", "test"), patch("app.qa.classify.gemini_client") as factory:
            client = factory.return_value.__enter__.return_value
            label = '{"category":"Theology","subcategory":"Prayer","tags":[]}'
            client.batches.create.return_value = types.BatchJob(state="JOB_STATE_SUCCEEDED", dest={
                "inlined_responses": [{"metadata": {"key": "1"}, "response": {
                    "candidates": [{"content": {"parts": [{"text": label}]}}]
                }}]
            })
            result = classify_batch(items, {})
            self.assertIsNone(result[0]["category"])
            self.assertEqual(result[1]["category"], "Theology")
            self.assertEqual(len(client.batches.create.call_args.kwargs["src"]), 2)
            client.models.generate_content.assert_not_called()

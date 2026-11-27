"""Configured Gemini Developer API client."""

from google import genai
from google.genai import types

from app.settings import get_settings


def gemini_client() -> genai.Client:
    return genai.Client(
        api_key=get_settings().GEMINI_API_KEY,
        http_options=types.HttpOptions(
            api_version="v1", timeout=20_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )

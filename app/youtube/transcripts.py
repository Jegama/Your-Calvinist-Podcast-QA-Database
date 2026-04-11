"""
Fetch transcripts from YouTube videos.
"""

from typing import Optional
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from urllib.parse import urlparse
from requests import Session
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from app.settings import get_settings


@dataclass
class TranscriptSegment:
    """A single segment of transcript with timing."""
    start: float  # Start time in seconds
    duration: float
    text: str


def _normalize_proxy_url(proxy_url: str) -> str:
    """Normalize proxy URL for requests/proxy libraries."""
    parsed = urlparse(proxy_url)

    if not parsed.scheme:
        return f"http://{proxy_url}"

    # ScraperAPI proxy endpoint is typically used over HTTP transport.
    # Using https:// here can trigger certificate verification failures.
    if parsed.scheme == "https" and "scraperapi.com" in parsed.netloc:
        return proxy_url.replace("https://", "http://", 1)

    return proxy_url


def _fetch_english_transcript(video_id: str, client_kwargs: dict):
    yt = YouTubeTranscriptApi(**client_kwargs)
    transcript_list = yt.list(video_id)

    try:
        transcript = transcript_list.find_transcript(['en'])
    except:
        transcript = transcript_list.find_generated_transcript(['en'])

    return transcript.fetch()


def get_raw_transcript(video_id: str) -> Optional[list[TranscriptSegment]]:
    """
    Fetches the transcript for a YouTube video.
    
    Tries to get manual English transcript first, falls back to auto-generated.
    
    Args:
        video_id: YouTube video ID (11 characters)
        
    Returns:
        List of TranscriptSegment objects, or None if unavailable
    """
    try:
        settings = get_settings()
        
        client_kwargs = {}
        proxy_url = ""

        if settings.YOUTUBE_PROXY:
            proxy_url = _normalize_proxy_url(settings.YOUTUBE_PROXY)
            client_kwargs["proxy_config"] = GenericProxyConfig(
                http_url=proxy_url,
                https_url=proxy_url,
            )

        http_client = None
        needs_http_client = bool(settings.YOUTUBE_COOKIES or settings.YOUTUBE_PROXY)
        if needs_http_client:
            http_client = Session()

            if not settings.YOUTUBE_PROXY_VERIFY_SSL:
                http_client.verify = False

        if settings.YOUTUBE_COOKIES and http_client is not None:
            cookie_jar = MozillaCookieJar(settings.YOUTUBE_COOKIES)
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            for cookie in cookie_jar:
                http_client.cookies.set_cookie(cookie)

        if http_client is not None:
            client_kwargs["http_client"] = http_client

        try:
            fetched = _fetch_english_transcript(video_id, client_kwargs)
        except Exception as fetch_error:
            error_text = str(fetch_error)
            cert_error = (
                "CERTIFICATE_VERIFY_FAILED" in error_text
                or "certificate verify failed" in error_text.lower()
            )
            has_proxy = bool(settings.YOUTUBE_PROXY)
            proxy_ssl_enabled = settings.YOUTUBE_PROXY_VERIFY_SSL

            if cert_error and has_proxy and proxy_ssl_enabled:
                print(
                    "Transcript warning: SSL verify failed with proxy; retrying with SSL verification disabled"
                )
                fallback_http_client = Session()
                fallback_http_client.verify = False

                if settings.YOUTUBE_COOKIES:
                    cookie_jar = MozillaCookieJar(settings.YOUTUBE_COOKIES)
                    cookie_jar.load(ignore_discard=True, ignore_expires=True)
                    for cookie in cookie_jar:
                        fallback_http_client.cookies.set_cookie(cookie)

                fallback_kwargs = dict(client_kwargs)
                fallback_kwargs["http_client"] = fallback_http_client
                fetched = _fetch_english_transcript(video_id, fallback_kwargs)
            else:
                raise
        
        segments = []
        for item in fetched:
            segments.append(TranscriptSegment(
                start=item.start,
                duration=getattr(item, "duration", 0.0),
                text=item.text,
            ))
        
        return segments
        
    except Exception as e:
        print(f"Transcript Error for {video_id}: {e}")
        return None


def transcript_to_raw_data(segments: list[TranscriptSegment]) -> list[dict]:
    """
    Convert TranscriptSegment list to JSON-serializable format for DB storage.

    Args:
        segments: List of TranscriptSegment objects

    Returns:
        List of dicts with start, duration, and text keys. Duration is
        persisted so reprocess-from-stored can compute accurate time windows
        (the slicer uses start + duration to bound the final question).
    """
    return [
        {"start": seg.start, "duration": seg.duration, "text": seg.text}
        for seg in segments
    ]


def transcript_to_full_text(segments: list[TranscriptSegment]) -> str:
    """
    Concatenate all transcript segments into a single text.
    
    Args:
        segments: List of TranscriptSegment objects
        
    Returns:
        Full transcript as a single string
    """
    return " ".join(seg.text for seg in segments)

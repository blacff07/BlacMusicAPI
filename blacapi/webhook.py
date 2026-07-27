# webhook.py — fire-and-forget POSTs for events a bot shouldn't have to
# poll for: a resolve exhausting every ladder rung and failing, or a
# /playlist request finishing. Deliberately its own tiny module (not
# reusing proxy.py's shared client) since proxy.py imports resolver.py —
# importing proxy.py back from here would be circular.

import asyncio
import time

import httpx

from blacapi.config import settings
from blacapi.logger import logger


async def _post(payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT) as client:
            await client.post(settings.WEBHOOK_URL, json=payload)
    except Exception as exc:
        # Never let a broken webhook endpoint affect resolution itself —
        # this is best-effort notification, not a dependency.
        logger.error(f"[webhook] failed to notify (event={payload.get('event')}): {exc}")


def notify_resolve_failure(video_id: str, status_code: int, reason: str) -> None:
    """Schedule the POST without blocking the caller. No-op if WEBHOOK_URL
    isn't configured."""
    if not settings.WEBHOOK_URL:
        return
    payload = {
        "event": "resolve_failed",
        "video_id": video_id,
        "status_code": status_code,
        "reason": reason,
        "ts": time.time(),
    }
    _schedule(payload)


def notify_playlist_processed(url: str, requested_limit: int, resolved_count: int) -> None:
    """Fires once a /playlist request finishes, so a bot queueing a whole
    playlist can get a single callback with the final count instead of
    polling. No-op if WEBHOOK_URL isn't configured."""
    if not settings.WEBHOOK_URL:
        return
    payload = {
        "event": "playlist_processed",
        "playlist_url": url,
        "requested_limit": requested_limit,
        "resolved_count": resolved_count,
        "ts": time.time(),
    }
    _schedule(payload)


def _schedule(payload: dict) -> None:
    try:
        asyncio.get_event_loop().create_task(_post(payload))
    except RuntimeError:
        # No running loop (shouldn't happen inside a request, but stay safe).
        pass

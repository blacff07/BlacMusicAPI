# metadata.py — search / info / playlist lookups.
#
# search/info use py_yt (a thin wrapper around YouTube's internal search API)
# rather than yt-dlp, because it's an order of magnitude faster for
# metadata-only lookups and never needs the n-signature/JS-runtime machinery
# that stream resolution does.
#
# Playlists are two-tier, mirroring the reference bot's own proven approach:
# py_yt's Playlist.get() first (richer metadata — duration, channel, etc.),
# falling back to yt-dlp's extract_flat (cheap page-scrape, no n-signature
# solving needed) when py_yt comes back empty, which happens for some
# playlists in practice.

import asyncio

import yt_dlp
from py_yt import Playlist, VideosSearch

from blacapi.config import settings
from blacapi.cache import TTLCache
from blacapi.logger import logger

_search_cache = TTLCache(ttl=settings.SEARCH_CACHE_TTL)
_info_cache = TTLCache(ttl=settings.SEARCH_CACHE_TTL)


def _duration_to_seconds(text: str) -> int:
    try:
        parts = str(text).split(":")
        seconds = 0
        for p in parts:
            seconds = seconds * 60 + int(p)
        return seconds
    except Exception:
        return 0


def _row(r: dict) -> dict:
    dur = r.get("duration") or "0:00"
    thumbs = r.get("thumbnails") or [{}]
    return {
        "id": r.get("id", ""),
        "title": r.get("title", ""),
        "url": r.get("link", ""),
        "duration": dur,
        "duration_sec": _duration_to_seconds(dur),
        "thumbnail": (thumbs[-1] or {}).get("url", "").split("?")[0],
        "channel": (r.get("channel") or {}).get("name", ""),
        "views": (r.get("viewCount") or {}).get("short", ""),
    }


def _row_from_flat_entry(e: dict) -> dict:
    """extract_flat entries are much thinner than py_yt's — no duration
    string, no channel object — so this fills in what's actually there."""
    duration_sec = e.get("duration") or 0
    minutes, seconds = divmod(int(duration_sec), 60)
    thumbs = e.get("thumbnails") or [{}]
    return {
        "id": e.get("id", ""),
        "title": e.get("title", ""),
        "url": e.get("url") or (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else ""),
        "duration": f"{minutes}:{seconds:02d}" if duration_sec else "0:00",
        "duration_sec": int(duration_sec),
        "thumbnail": (thumbs[-1] or {}).get("url", ""),
        "channel": e.get("channel") or e.get("uploader") or "",
        "views": str(e.get("view_count") or ""),
    }


async def search(query: str, limit: int = 5) -> list[dict]:
    key = f"{query.strip().lower()}:{limit}"
    cached = _search_cache.get(key)
    if cached is not None:
        return cached
    try:
        results = await VideosSearch(query, limit=limit).next()
        rows = [_row(r) for r in results.get("result", [])]
    except Exception as exc:
        logger.error(f"[search] '{query}': {exc}")
        rows = []
    _search_cache.set(key, rows)
    return rows


def _row_from_ytdlp_info(info: dict) -> dict:
    duration_sec = int(info.get("duration") or 0)
    minutes, seconds = divmod(duration_sec, 60)
    thumbnail = info.get("thumbnail") or (info.get("thumbnails") or [{}])[-1].get("url", "")
    return {
        "id": info.get("id", ""),
        "title": info.get("title", ""),
        "url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info.get('id', '')}",
        "duration": f"{minutes}:{seconds:02d}" if duration_sec else "0:00",
        "duration_sec": duration_sec,
        "thumbnail": thumbnail,
        "channel": info.get("channel") or info.get("uploader") or "",
        "views": str(info.get("view_count") or ""),
    }


async def get_info(video_id: str) -> dict | None:
    """Look up a specific video's metadata by ID.

    Deliberately NOT implemented via py_yt's VideosSearch — passing a video
    URL to a text-search API just returns whatever happens to rank for that
    string, not the actual video (confirmed in testing: it returned an
    unrelated video whose title literally contained the URL). yt-dlp's
    extract_flat looks up the exact ID directly and is still cheap/fast —
    no n-signature solving needed since we don't need playable format URLs.
    """
    cached = _info_cache.get(video_id)
    if cached is not None:
        return cached

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }

    def _extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _extract)
    except Exception as exc:
        logger.error(f"[get_info] {video_id}: {exc}")
        return None
    if not info:
        return None

    row = _row_from_ytdlp_info(info)
    _info_cache.set(video_id, row)
    return row


async def get_related(video_id: str, limit: int = 10) -> list[dict]:
    """"Related" / watch-next style recommendations.

    yt-dlp's info_dict.get("related_videos") is frequently empty in
    current YouTube extraction (the field was reliable years ago, isn't
    now), so this tries it first and, when it comes back empty, falls
    back to a plain title/channel search seeded from the source video's
    own metadata — same-artist/similar-title results rather than a true
    recommendation graph, but never a dead end.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }

    def _extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _extract)
    except Exception as exc:
        logger.error(f"[get_related] {video_id}: {exc}")
        info = None

    related = (info or {}).get("related_videos") or []
    if related:
        rows = [_row_from_flat_entry(e) for e in related if e and e.get("id")][:limit]
        if rows:
            return rows

    # Fallback: search using the source video's own title/channel as the
    # query, excluding the source video itself from the results.
    seed_title = (info or {}).get("title") or ""
    seed_channel = (info or {}).get("channel") or (info or {}).get("uploader") or ""
    query = f"{seed_channel} {seed_title}".strip() or video_id
    try:
        results = await search(query, limit + 1)
    except Exception as exc:
        logger.error(f"[get_related] fallback search failed for {video_id}: {exc}")
        return []
    return [r for r in results if r.get("id") != video_id][:limit]


async def _flat_playlist_entries(url: str, limit: int) -> list[dict]:
    """List playlist entries cheaply via yt-dlp extract_flat (no download).

    extract_flat only scrapes page metadata — it never solves the
    n-signature challenge, so it's far more reliable than full extraction
    for a simple "what's in this playlist" listing, and stays cookieless.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": False,
        "extractor_args": {"youtube": {"player_client": settings.PLAYER_CLIENTS}},
    }

    def _extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries") or []
        return [e for e in entries if e and e.get("id")][:limit]

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _extract)


async def get_playlist(url: str, limit: int = 50) -> list[dict]:
    rows: list[dict] = []
    try:
        plist = await Playlist.get(url)
        rows = [_row(v) for v in (plist.get("videos") or [])[:limit]]
    except Exception as exc:
        logger.error(f"[get_playlist] py_yt failed for '{url}': {exc}")

    if not rows:
        try:
            entries = await _flat_playlist_entries(url, limit)
            rows = [_row_from_flat_entry(e) for e in entries]
        except Exception as exc:
            logger.error(f"[get_playlist] yt-dlp fallback failed for '{url}': {exc}")

    return rows[:limit]

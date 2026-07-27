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

_search_cache = TTLCache(ttl=settings.SEARCH_CACHE_TTL, name="search")
_info_cache = TTLCache(ttl=settings.SEARCH_CACHE_TTL, name="info")


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

    def _opts(use_cookies: bool = False) -> dict:
        o = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": True,
        }
        if use_cookies and settings.YT_COOKIES_FILE:
            o["cookiefile"] = settings.YT_COOKIES_FILE
        return o

    def _extract(use_cookies: bool = False):
        with yt_dlp.YoutubeDL(_opts(use_cookies)) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    loop = asyncio.get_event_loop()
    info = None
    last_exc = None
    # A bare watch-page lookup has no fallback of its own (unlike the full
    # resolver ladder used for playback) — under concurrent load, e.g.
    # /info/batch firing several of these at once from the same IP, a
    # transient empty response for one id is common enough that a single
    # unretried attempt isn't reliable. One quick retry clears the vast
    # majority of these without meaningfully slowing down the normal,
    # single-lookup case.
    for attempt in range(2):
        try:
            info = await loop.run_in_executor(None, _extract)
            if info:
                break
        except Exception as exc:
            last_exc = exc
            info = None
        if attempt == 0:
            await asyncio.sleep(0.4)

    # Cookie fallback: only reached if both cookieless attempts failed, and
    # only does anything if YT_COOKIES is configured. This is the one thing
    # that actually gets past YouTube's "sign in to confirm you're not a
    # bot" wall on certain videos — retrying the cookieless request again
    # doesn't help there, since that failure isn't transient.
    if not info and settings.YT_COOKIES_FILE:
        try:
            info = await loop.run_in_executor(None, _extract, True)
        except Exception as exc:
            last_exc = exc

    if not info:
        if last_exc:
            logger.error(f"[get_info] {video_id}: {last_exc}")
        return None

    row = _row_from_ytdlp_info(info)
    _info_cache.set(video_id, row)
    return row


async def get_info_batch(video_ids: list[str]) -> list[dict]:
    """Resolve several videos' metadata concurrently instead of forcing a
    bot to make N sequential /info calls for a queue. Each id's own cache
    entry (see get_info) is still used/populated individually, so a mixed
    batch of cached + uncached ids only pays the extraction cost for the
    uncached ones.

    A failed lookup doesn't fail the whole batch — it comes back as its
    own {"id": ..., "error": ...} entry so the caller can see exactly
    which ids in the queue didn't resolve.
    """
    async def _one(video_id: str) -> dict:
        try:
            row = await get_info(video_id)
        except Exception as exc:
            return {"id": video_id, "error": str(exc)}
        if not row:
            return {"id": video_id, "error": "not found"}
        return row

    return list(await asyncio.gather(*(_one(v) for v in video_ids)))


async def get_related(video_id: str, limit: int = 10) -> list[dict]:
    """"Related" / watch-next style recommendations.

    yt-dlp's info_dict.get("related_videos") is frequently empty in
    current YouTube extraction (the field was reliable years ago, isn't
    now), so this tries it first and, when it comes back empty, falls
    back to a plain title/channel search seeded from the source video's
    own metadata — same-artist/similar-title results rather than a true
    recommendation graph, but never a dead end.
    """
    def _opts(use_cookies: bool = False) -> dict:
        o = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": True,
        }
        if use_cookies and settings.YT_COOKIES_FILE:
            o["cookiefile"] = settings.YT_COOKIES_FILE
        return o

    def _extract(use_cookies: bool = False):
        with yt_dlp.YoutubeDL(_opts(use_cookies)) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    loop = asyncio.get_event_loop()
    info = None
    # Same reasoning as get_info(): a single unretried attempt is prone to
    # transient empty responses, especially since /related often gets
    # called right alongside a batch of other lookups for the same queue.
    for attempt in range(2):
        try:
            info = await loop.run_in_executor(None, _extract)
            if info:
                break
        except Exception as exc:
            logger.error(f"[get_related] {video_id}: {exc}")
            info = None
        if attempt == 0:
            await asyncio.sleep(0.4)

    # Same cookie fallback as get_info() — needed for the source video
    # itself if it's one that requires it, before we even get to computing
    # related results.
    if not info and settings.YT_COOKIES_FILE:
        try:
            info = await loop.run_in_executor(None, _extract, True)
        except Exception as exc:
            logger.error(f"[get_related] {video_id} (cookie tier): {exc}")

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
    def _opts(use_cookies: bool = False) -> dict:
        o = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": False,
            "extractor_args": {"youtube": {"player_client": settings.PLAYER_CLIENTS}},
        }
        if use_cookies and settings.YT_COOKIES_FILE:
            o["cookiefile"] = settings.YT_COOKIES_FILE
        return o

    def _extract(use_cookies: bool = False):
        with yt_dlp.YoutubeDL(_opts(use_cookies)) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get("entries") or []
        return [e for e in entries if e and e.get("id")][:limit]

    loop = asyncio.get_event_loop()
    last_exc = None
    # Same reasoning as get_info()/get_related(): a single unretried
    # yt-dlp call is prone to transient empty/blocked responses. This is
    # the last fallback tier (after py_yt already failed in get_playlist),
    # so it's worth one retry before giving up entirely.
    for attempt in range(2):
        try:
            return await loop.run_in_executor(None, _extract)
        except Exception as exc:
            last_exc = exc
        if attempt == 0:
            await asyncio.sleep(0.4)

    if settings.YT_COOKIES_FILE:
        try:
            return await loop.run_in_executor(None, _extract, True)
        except Exception as exc:
            last_exc = exc

    raise last_exc


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

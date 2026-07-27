# lyrics.py — lyrics lookup, paired naturally with an audio API.
#
# Backed by lyrics.ovh (a free, keyless public API) rather than anything
# requiring its own account/API key, to match this project's "no extra
# accounts to manage" philosophy. It expects a separate artist + title,
# so a single freeform query is split heuristically before the lookup.

import re
from urllib.parse import quote

import httpx

from blacapi.cache import TTLCache
from blacapi.logger import logger

_LYRICS_CACHE = TTLCache(ttl=86400, name="lyrics")  # lyrics don't change; cache a full day
_LYRICS_API = "https://api.lyrics.ovh/v1/{artist}/{title}"

# Strips the noise common in YouTube music-video titles before treating
# the remainder as "artist - title" — e.g. "(Official Video)", "[4K]",
# "(Lyrics)" — none of that helps a lyrics lookup and often breaks it.
_NOISE_RE = re.compile(
    r"\(.*?(official|lyrics?|audio|video|remaster|hd|4k|visualizer).*?\)"
    r"|\[.*?(official|lyrics?|audio|video|remaster|hd|4k|visualizer).*?\]",
    re.IGNORECASE,
)


def split_artist_title(query: str) -> tuple[str, str]:
    """Best-effort split of a freeform query into (artist, title).

    Handles the two common shapes directly ("Artist - Title", "Title by
    Artist"); anything else is passed through as the title with an empty
    artist, which the caller resolves via a YouTube search fallback.
    """
    cleaned = _NOISE_RE.sub("", query).strip(" -|")
    if " - " in cleaned:
        artist, title = cleaned.split(" - ", 1)
        return artist.strip(), title.strip()
    m = re.search(r"^(.*)\bby\b(.*)$", cleaned, re.IGNORECASE)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return "", cleaned.strip()


async def fetch_lyrics(artist: str, title: str) -> str | None:
    if not artist or not title:
        return None
    key = f"{artist.lower()}:{title.lower()}"
    cached = _LYRICS_CACHE.get(key)
    if cached is not None:
        return cached or None  # cached "" means "looked up, not found"

    url = _LYRICS_API.format(artist=quote(artist, safe=""), title=quote(title, safe=""))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        if resp.status_code == 404:
            _LYRICS_CACHE.set(key, "")
            return None
        resp.raise_for_status()
        lyrics = (resp.json() or {}).get("lyrics", "").strip()
        _LYRICS_CACHE.set(key, lyrics)
        return lyrics or None
    except Exception as exc:
        logger.error(f"[lyrics] lookup failed for '{artist} - {title}': {exc}")
        return None

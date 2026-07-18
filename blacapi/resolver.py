# resolver.py — the actual "how do we get bytes out of YouTube" engine.
#
# Design goals (see README for the full rationale):
#   - Cookieless by default. A layered client/geo-spoofing ladder handles
#     normal videos, age-restricted videos, and region-locked videos without
#     ever touching a cookie file.
#   - yt-dlp only ever *resolves* a direct googlevideo URL here (skip_download
#     extract_info) — it never downloads to disk. The route layer proxies the
#     bytes straight through to the caller. No disk I/O = works fine on a
#     512MB VPS and scales to many concurrent listeners.
#   - Every resolution is cached for URL_CACHE_TTL and de-duplicated with a
#     per-video-id lock, so N concurrent requests for the same track only
#     ever trigger one yt-dlp extraction.
#   - Failures are raised as classified ResolutionError subclasses (see
#     errors.py) rather than swallowed into a generic 404 — the caller gets
#     an accurate status code and a real reason, and every failure is logged.

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import yt_dlp

from blacapi.cache import KeyedLocks, TTLCache
from blacapi.config import settings
from blacapi.errors import ResolutionError, VideoNotFoundError, classify
from blacapi.logger import logger

YT_WATCH = "https://www.youtube.com/watch?v="

# Matches an 11-char YouTube video id, optionally embedded in a full URL.
_ID_ONLY_RE = re.compile(r"^[A-Za-z0-9_-]{10,12}$")
_ID_IN_URL_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([A-Za-z0-9_-]{10,12})")

# yt-dlp 2024.x+ solves YouTube's n-signature challenge with an embedded JS
# runtime. The default auto-detected runtime is unreliable in containers and
# silently degrades to "Sign in to confirm you're not a bot" — Node must be
# installed in the image (see Dockerfile) and selected explicitly.
JS_RUNTIMES = {"node": {}}

_AGE_ERROR_MARKERS = (
    "confirm your age", "age-restricted", "sign in to confirm your age",
    "inappropriate", "age restricted",
)
_GEO_ERROR_MARKERS = (
    "not available in your country", "not available on this app",
    "content isn't available", "blocked it in your country", "geo",
)

_url_cache = TTLCache(ttl=settings.URL_CACHE_TTL)
_locks = KeyedLocks()
_resolve_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_RESOLVES)


def extract_video_id(value: str) -> str:
    value = value.strip()
    if _ID_ONLY_RE.match(value):
        return value
    m = _ID_IN_URL_RE.search(value)
    if m:
        return m.group(1)
    return value


@dataclass
class StreamResult:
    kind: str                          # "audio" | "video"
    url: str
    audio_url: Optional[str] = None    # populated only when needs_mux is True
    needs_mux: bool = False
    is_hls: bool = False               # url is an HLS manifest, not a direct file — needs ffmpeg remux
    ext: str = "mp4"
    format_id: str = ""
    resolved_at: float = field(default_factory=time.monotonic)


def _is_age_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _AGE_ERROR_MARKERS)


def _is_geo_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _GEO_ERROR_MARKERS)


def _ydl_opts(
    fmt_selector: str,
    player_clients: list,
    geo_country: Optional[str] = None,
    use_cookies: bool = False,
) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "skip_download": True,
        "socket_timeout": settings.RESOLVE_TIMEOUT,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "format": fmt_selector,
        "extractor_args": {"youtube": {"player_client": player_clients}},
        "js_runtimes": JS_RUNTIMES,
    }
    if geo_country:
        opts["geo_bypass_country"] = geo_country
    # Only attached when YT_COOKIES is set AND this specific call opts in
    # (last-resort tier below) — every normal request stays cookieless.
    if use_cookies and settings.YT_COOKIES_FILE:
        opts["cookiefile"] = settings.YT_COOKIES_FILE
    return opts


def _extract_sync(
    video_id: str,
    fmt_selector: str,
    player_clients: list,
    geo_country: Optional[str] = None,
    use_cookies: bool = False,
) -> Optional[dict]:
    url = YT_WATCH + video_id
    opts = _ydl_opts(fmt_selector, player_clients, geo_country, use_cookies)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError:
            # Strict selector failed (some videos only expose formats behind
            # a PO token) — fall back to the broadest possible selection so
            # we can still hand back *something* playable.
            ydl.params["format"] = "best"
            return ydl.extract_info(url, download=False)


async def _extract_once(
    video_id: str,
    fmt_selector: str,
    player_clients: list,
    geo_country: Optional[str] = None,
    use_cookies: bool = False,
) -> Optional[dict]:
    loop = asyncio.get_event_loop()
    async with _resolve_semaphore:
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    None, _extract_sync, video_id, fmt_selector, player_clients, geo_country, use_cookies
                ),
                timeout=settings.RESOLVE_TIMEOUT + 10,
            )
        except asyncio.TimeoutError:
            # Note: the background thread is not forcibly killed here (Python
            # can't safely do that) — it will keep running to completion on
            # its own and simply has its result discarded. This exception
            # just stops *this request* from waiting on it any longer.
            logger.error(
                f"[resolver] {video_id}: extraction exceeded "
                f"{settings.RESOLVE_TIMEOUT + 10}s with clients={player_clients} "
                f"geo={geo_country or '-'} — check that Node.js/ffmpeg are "
                f"installed, and that this server's IP isn't being throttled "
                f"by YouTube (common on cloud/datacenter IP ranges)."
            )
            raise


async def _extract(video_id: str, fmt_selector: str) -> dict:
    """Resolve a video's info dict, escalating through a bypass ladder:

    1. Normal client spoofing (covers the vast majority of videos).
    2. If that looks like an age-gate error: retry with tv_embedded/android,
       which are never shown YouTube's age-verification prompt.
    3. If that looks like a region-lock error: retry cycling through a short
       list of geo_bypass_country codes.

    Each rung is a single extra yt-dlp call, so a normal video is never
    slowed down by this — only videos that actually need the bypass pay for
    it. Every terminal failure is logged and raised as a classified
    ResolutionError so the route layer can return an accurate status code.
    """
    try:
        info = await _extract_once(video_id, fmt_selector, settings.PLAYER_CLIENTS)
        if info:
            return info
        last_exc: Exception = VideoNotFoundError(f"yt-dlp returned no info for {video_id}")
    except Exception as exc:
        last_exc = exc
        if _is_age_error(exc):
            logger.info(f"[resolver] {video_id}: age-gated, retrying with embedded client")
            try:
                info = await _extract_once(video_id, fmt_selector, settings.AGE_BYPASS_CLIENTS)
                if info:
                    return info
            except Exception as exc2:
                last_exc = exc2

        if _is_geo_error(last_exc):
            for country in settings.GEO_BYPASS_COUNTRIES:
                logger.info(f"[resolver] {video_id}: geo-blocked, retrying as {country}")
                try:
                    info = await _extract_once(
                        video_id, fmt_selector, settings.AGE_BYPASS_CLIENTS, geo_country=country
                    )
                    if info:
                        return info
                except Exception as exc3:
                    last_exc = exc3
                    continue

        # Final rung: only reached if every cookieless attempt above failed,
        # and only does anything if YT_COOKIES was explicitly configured.
        if settings.YT_COOKIES_FILE:
            logger.info(f"[resolver] {video_id}: retrying with configured cookies")
            try:
                info = await _extract_once(
                    video_id, fmt_selector, settings.PLAYER_CLIENTS, use_cookies=True
                )
                if info:
                    return info
            except Exception as exc4:
                last_exc = exc4

    classified = classify(last_exc)
    logger.error(f"[resolver] {video_id}: resolution failed ({classified.status_code}): {classified}")
    raise classified


# Formats with these protocols are manifests (a playlist of further URLs),
# not a single directly byte-servable/Range-able file — our reverse-proxy
# design needs the latter. yt-dlp still tags these with acodec/vcodec set,
# so they'd otherwise slip past the audio/video-only filters below and hand
# back an .m3u8/.mpd manifest URL instead of real media bytes.
_MANIFEST_PROTOCOLS = {"m3u8", "m3u8_native", "http_dash_segments", "http_dash_segments_generic"}


def _is_direct(f: dict) -> bool:
    return f.get("protocol") not in _MANIFEST_PROTOCOLS


def _pick_hls_combined(info: dict, max_height: Optional[int] = None) -> Optional[dict]:
    """Best HLS (m3u8) variant with both audio+video muxed in the manifest —
    ffmpeg can consume this directly and remux it to a normal stream, so
    this is a last-resort tier when YouTube offers no direct/DASH formats
    at all for this video or this server's IP."""
    formats = (info or {}).get("formats") or []
    hls = [
        f for f in formats
        if f.get("protocol") in _MANIFEST_PROTOCOLS
        and f.get("acodec") not in (None, "none")
        and f.get("vcodec") not in (None, "none")
        and f.get("url")
    ]
    if max_height:
        under_cap = [f for f in hls if (f.get("height") or 0) <= max_height]
        hls = under_cap or hls  # fall back to whatever exists if nothing fits under the cap
    if not hls:
        return None
    hls.sort(key=lambda f: f.get("height") or 0, reverse=True)
    return hls[0]


def _pick_best_audio(info: dict) -> Optional[dict]:
    if not info:
        return None
    # A pure audio-only extraction sometimes returns the format at top level.
    if (
        info.get("acodec") not in (None, "none")
        and info.get("vcodec") in (None, "none")
        and info.get("url")
        and _is_direct(info)
    ):
        return info
    candidates = [
        f for f in (info.get("formats") or [])
        if f.get("acodec") not in (None, "none")
        and f.get("vcodec") in (None, "none")
        and f.get("url")
        and _is_direct(f)
    ]
    if not candidates:
        return None
    # itag 140 (m4a ~128kbps) is the widest-compatible, bandwidth-sane
    # sweet spot for ffmpeg — good enough for voice-chat playback without
    # pulling a needlessly large stream.
    for f in candidates:
        if str(f.get("format_id")) == "140":
            return f
    candidates.sort(key=lambda f: f.get("abr") or 0, reverse=True)
    return candidates[0]


async def resolve_audio(video_id: str, force: bool = False) -> StreamResult:
    cache_key = f"a:{video_id}"
    if not force:
        cached = _url_cache.get(cache_key)
        if cached:
            return cached

    lock = await _locks.get(cache_key)
    async with lock:
        if not force:
            cached = _url_cache.get(cache_key)
            if cached:
                return cached

        info = await _extract(video_id, "bestaudio/best")

        fmt = _pick_best_audio(info)
        if fmt and fmt.get("url"):
            result = StreamResult(
                kind="audio",
                url=fmt["url"],
                ext=fmt.get("ext", "m4a"),
                format_id=str(fmt.get("format_id", "")),
            )
            _url_cache.set(cache_key, result)
            return result

        # No direct audio-only stream — YouTube is sometimes only offering
        # HLS-muxed variants (observed on some datacenter IPs). ffmpeg can
        # read the HLS manifest directly and remux just the audio track.
        hls_fmt = _pick_hls_combined(info)
        if hls_fmt and hls_fmt.get("url"):
            logger.info(f"[resolver] {video_id}: no direct audio stream, falling back to HLS remux")
            result = StreamResult(
                kind="audio",
                url=hls_fmt["url"],
                is_hls=True,
                ext="m4a",
                format_id=str(hls_fmt.get("format_id", "")),
            )
            _url_cache.set(cache_key, result)
            return result

        raise VideoNotFoundError(f"No audio-only stream found for {video_id}")


def _pick_progressive_video(info: dict, max_height: int) -> Optional[dict]:
    formats = (info or {}).get("formats") or []
    progressive = [
        f for f in formats
        if f.get("acodec") not in (None, "none")
        and f.get("vcodec") not in (None, "none")
        and f.get("url")
        and _is_direct(f)
        and (f.get("height") or 0) <= max_height
    ]
    if not progressive:
        return None
    progressive.sort(key=lambda f: f.get("height") or 0, reverse=True)
    return progressive[0]


async def resolve_video(video_id: str, max_height: int, force: bool = False) -> StreamResult:
    max_height = min(max_height, settings.VIDEO_MAX_HEIGHT_CEILING)
    cache_key = f"v{max_height}:{video_id}"
    if not force:
        cached = _url_cache.get(cache_key)
        if cached:
            return cached

    lock = await _locks.get(cache_key)
    async with lock:
        if not force:
            cached = _url_cache.get(cache_key)
            if cached:
                return cached

        selector = (
            f"best[height<={max_height}][acodec!=none][vcodec!=none]/"
            f"best[acodec!=none][vcodec!=none]"
        )
        info = await _extract(video_id, selector)

        fmt = _pick_progressive_video(info, max_height)
        if fmt:
            result = StreamResult(
                kind="video", url=fmt["url"],
                ext=fmt.get("ext", "mp4"), format_id=str(fmt.get("format_id", "")),
            )
            _url_cache.set(cache_key, result)
            return result

        # No single muxed (progressive) format under this height — YouTube
        # increasingly serves separate video/audio DASH streams only. Resolve
        # both and let the route layer mux them on the fly with ffmpeg
        # (stream-copy, no re-encode — cheap even on a small VPS, and no
        # wasted bandwidth pulling a higher bitrate than requested).
        info2 = await _extract(
            video_id,
            f"bestvideo[height<={max_height}]+bestaudio/bestvideo+bestaudio/best",
        )

        reqs = info2.get("requested_formats")
        if reqs and len(reqs) >= 2:
            direct_reqs = [f for f in reqs if _is_direct(f)]
            if len(direct_reqs) >= 2:
                video_fmt = next((f for f in direct_reqs if f.get("vcodec") not in (None, "none")), direct_reqs[0])
                audio_fmt = next(
                    (f for f in direct_reqs if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")),
                    direct_reqs[-1],
                )
                if video_fmt.get("url") and audio_fmt.get("url"):
                    result = StreamResult(
                        kind="video",
                        url=video_fmt["url"],
                        audio_url=audio_fmt["url"],
                        needs_mux=True,
                        ext="mp4",
                        format_id=str(video_fmt.get("format_id", "")),
                    )
                    _url_cache.set(cache_key, result)
                    return result

        if info2.get("url") and _is_direct(info2):
            result = StreamResult(kind="video", url=info2["url"], ext=info2.get("ext", "mp4"))
            _url_cache.set(cache_key, result)
            return result

        # Still nothing direct — last resort is an HLS-muxed variant, which
        # ffmpeg can consume and remux to a normal stream on the fly.
        hls_fmt = _pick_hls_combined(info2, max_height) or _pick_hls_combined(info, max_height)
        if hls_fmt and hls_fmt.get("url"):
            logger.info(f"[resolver] {video_id}: no direct/DASH video stream, falling back to HLS remux")
            result = StreamResult(
                kind="video", url=hls_fmt["url"], is_hls=True,
                ext="mp4", format_id=str(hls_fmt.get("format_id", "")),
            )
            _url_cache.set(cache_key, result)
            return result

        raise VideoNotFoundError(
            f"No direct (non-HLS/manifest) playable video stream found for {video_id} — "
            "YouTube may only be offering HLS-only formats for this video/IP"
        )


def invalidate_audio(video_id: str) -> None:
    _url_cache.invalidate(f"a:{video_id}")


def invalidate_video(video_id: str, max_height: int) -> None:
    max_height = min(max_height, settings.VIDEO_MAX_HEIGHT_CEILING)
    _url_cache.invalidate(f"v{max_height}:{video_id}")


async def list_audio_formats(video_id: str, limit: int = 8) -> list[dict]:
    """Several candidate audio URLs+itags — powers the JSON /audio endpoint's
    multi-quality fallback list, so a bot can drop to a lower bitrate on
    network jitter without a fresh resolution round-trip."""
    info = await _extract(video_id, "bestaudio/best")
    out = []
    for f in info.get("formats") or []:
        if (
            f.get("acodec") not in (None, "none")
            and f.get("vcodec") in (None, "none")
            and f.get("url")
            and _is_direct(f)
        ):
            out.append({
                "format_id": str(f.get("format_id", "")),
                "ext": f.get("ext"),
                "abr": f.get("abr"),
                "url": f["url"],
            })
    out.sort(key=lambda f: f.get("abr") or 0, reverse=True)

    if not out:
        # No direct audio-only format at all — offer the HLS manifest as a
        # last resort. It's not a raw byte stream, but ffmpeg (and therefore
        # any pytgcalls/ffmpeg-based bot) can take an .m3u8 URL directly as
        # an input, so this is still genuinely usable rather than a dead end.
        hls_fmt = _pick_hls_combined(info)
        if hls_fmt and hls_fmt.get("url"):
            out.append({
                "format_id": "hls_manifest",
                "ext": "m3u8",
                "abr": None,
                "url": hls_fmt["url"],
                "note": "HLS manifest, not a raw file — pass directly to ffmpeg as an input (e.g. `ffmpeg -i <url> ...`), extract the audio track with -vn.",
            })

    if not out:
        raise VideoNotFoundError(f"No audio streams found for {video_id}")
    return out[:limit]


async def list_video_qualities(video_id: str, heights: list[int]) -> list[dict]:
    """Resolve several video qualities for the multi-quality fallback list on
    /api/youtube/stream. Best-effort: a height that fails to resolve is
    silently skipped rather than failing the whole request."""
    out = []
    for h in heights:
        try:
            result = await resolve_video(video_id, h)
        except ResolutionError:
            continue
        if result.needs_mux:
            continue  # only single-file URLs are safe to hand back as JSON
        out.append({"height": h, "url": result.url, "format_id": result.format_id, "ext": result.ext})
    return out

# youtube.py — Core YouTube engine for Blac Music API
#
# Key design:
#   - Cookieless first: no cookies needed for most content. Falls back on 403/age errors.
#   - Per-video lock: only one download runs per video_id. Second caller waits, then gets cache.
#   - Global semaphore: caps simultaneous yt-dlp processes (set via MAX_CONCURRENT_DOWNLOADS).
#   - In-memory cache: search and info results cached to avoid repeated YouTube calls.
#   - Disk cache: already-downloaded files returned instantly with no re-download.

import asyncio
import glob
import os
import re
import time
from pathlib import Path
from typing import Optional

import yt_dlp
from py_yt import Playlist, VideosSearch

from blacapi.core.config import settings
from blacapi.core.cookies import cookie_manager
from blacapi.core.logger import logger


YT_BASE = "https://www.youtube.com/watch?v="

_YT_URL_RE = re.compile(
    r"(https?://)?(www\.|m\.|music\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|live/|embed/|playlist\?list=)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
)

_VIDEO_EXTS = frozenset({".mp4", ".mkv", ".webm", ".mov"})
_AUDIO_EXTS = frozenset({".m4a", ".webm", ".opus", ".mp3", ".ogg", ".flac"})
_SKIP_EXTS  = frozenset({".part", ".ytdl", ".info.json", ".temp", ".json", ".tmp"})

_AUTH_ERRORS = (
    "sign in", "age", "403", "private video",
    "video unavailable", "login required", "not available",
    "confirm your age", "inappropriate",
)


def _t2s(t: str) -> int:
    try:
        return sum(int(x) * 60 ** i for i, x in enumerate(reversed(str(t).split(":"))))
    except Exception:
        return 0


def is_youtube_url(url: str) -> bool:
    return bool(_YT_URL_RE.match(url.strip()))


def extract_video_id(link: str) -> str:
    link = link.strip()
    if "v=" in link:
        return link.split("v=")[-1].split("&")[0].split("?")[0]
    if "youtu.be/" in link:
        return link.split("youtu.be/")[-1].split("?")[0].split("&")[0]
    if "shorts/" in link:
        return link.split("shorts/")[-1].split("?")[0]
    if "live/" in link:
        return link.split("live/")[-1].split("?")[0]
    if re.match(r"^[A-Za-z0-9_-]{11}$", link):
        return link
    return link


def _locate_file(video_id: str, video: bool = False) -> Optional[str]:
    pattern    = os.path.join(settings.DOWNLOAD_DIR, f"{video_id}*")
    candidates = [
        p for p in glob.glob(pattern)
        if os.path.isfile(p)
        and Path(p).suffix.lower() not in _SKIP_EXTS
        and os.path.getsize(p) > 1024
    ]
    target_exts = _VIDEO_EXTS if video else _AUDIO_EXTS
    for p in sorted(candidates):
        if Path(p).suffix.lower() in target_exts:
            return p
    if not video:
        for p in sorted(candidates):
            if Path(p).suffix.lower() in _VIDEO_EXTS:
                return p
    return None


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _AUTH_ERRORS)


# --- Search ---

_search_cache: dict[str, tuple[list, float]] = {}
_search_lock = asyncio.Lock()


async def search_youtube(query: str, limit: int = 5) -> list[dict]:
    key    = f"{query.lower().strip()}:{limit}"
    cached = _search_cache.get(key)
    if cached and time.monotonic() - cached[1] < settings.SEARCH_CACHE_TTL:
        return cached[0]

    async with _search_lock:
        cached = _search_cache.get(key)
        if cached and time.monotonic() - cached[1] < settings.SEARCH_CACHE_TTL:
            return cached[0]
        results = await asyncio.to_thread(_sync_search, query, limit)
        _search_cache[key] = (results, time.monotonic())
        if len(_search_cache) > 2000:
            cutoff = time.monotonic() - settings.SEARCH_CACHE_TTL
            for k in [k for k, v in list(_search_cache.items()) if v[1] < cutoff]:
                _search_cache.pop(k, None)
        return results


def _sync_search(query: str, limit: int) -> list[dict]:
    try:
        vs   = VideosSearch(query, limit=limit)
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(vs.next())
        finally:
            loop.close()
        out = []
        for r in raw.get("result", []):
            dur_str = r.get("duration") or "0:00"
            thumbs  = r.get("thumbnails") or [{}]
            out.append({
                "title":        r.get("title", ""),
                "id":           r.get("id", ""),
                "url":          r.get("link", ""),
                "duration":     dur_str,
                "duration_sec": _t2s(dur_str),
                "thumbnail":    thumbs[0].get("url", "").split("?")[0],
                "channel":      (r.get("channel") or {}).get("name", ""),
                "views":        (r.get("viewCount") or {}).get("text", ""),
            })
        return out
    except Exception as exc:
        logger.error(f"Search error for '{query}': {exc}")
        return []


# --- Info ---

_info_cache: dict[str, tuple[dict, float]] = {}


async def get_video_info(video_id: str) -> Optional[dict]:
    cached = _info_cache.get(video_id)
    if cached and time.monotonic() - cached[1] < settings.SEARCH_CACHE_TTL:
        return cached[0]
    url = YT_BASE + video_id
    try:
        vs  = VideosSearch(url, limit=1)
        raw = (await vs.next()).get("result", [])
        if not raw:
            return None
        r       = raw[0]
        dur_str = r.get("duration") or "0:00"
        thumbs  = r.get("thumbnails") or [{}]
        info = {
            "title":        r.get("title", ""),
            "id":           r.get("id", video_id),
            "url":          r.get("link", url),
            "duration":     dur_str,
            "duration_sec": _t2s(dur_str),
            "thumbnail":    thumbs[0].get("url", "").split("?")[0],
            "channel":      (r.get("channel") or {}).get("name", ""),
            "views":        (r.get("viewCount") or {}).get("text", ""),
        }
        _info_cache[video_id] = (info, time.monotonic())
        return info
    except Exception as exc:
        logger.error(f"Info error for {video_id}: {exc}")
        return None


# --- Playlist ---

async def get_playlist_ids(playlist_url: str, limit: int = 50) -> list[str]:
    try:
        plist  = await Playlist.get(playlist_url)
        videos = plist.get("videos") or []
        return [v["id"] for v in videos[:limit] if v.get("id")]
    except Exception as exc:
        logger.error(f"Playlist error for '{playlist_url}': {exc}")
        return []


# --- Download ---

_dl_semaphore: Optional[asyncio.Semaphore] = None
_dl_locks:     dict[str, asyncio.Lock]     = {}
_dl_locks_meta = asyncio.Lock()


def _get_semaphore() -> asyncio.Semaphore:
    global _dl_semaphore
    if _dl_semaphore is None:
        _dl_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
    return _dl_semaphore


async def _get_video_lock(video_id: str) -> asyncio.Lock:
    async with _dl_locks_meta:
        if video_id not in _dl_locks:
            _dl_locks[video_id] = asyncio.Lock()
        lock = _dl_locks[video_id]
        idle = [k for k, v in _dl_locks.items() if not v.locked() and k != video_id]
        for k in idle[:50]:
            _dl_locks.pop(k, None)
        return lock


async def download_track(video_id: str, video: bool = False) -> Optional[str]:
    existing = _locate_file(video_id, video=video)
    if existing:
        return existing

    url  = YT_BASE + video_id
    lock = await _get_video_lock(video_id)

    async with lock:
        existing = _locate_file(video_id, video=video)
        if existing:
            return existing
        async with _get_semaphore():
            return await asyncio.to_thread(_sync_download, url, video_id, video)


def _build_ydl_opts(video: bool, cookie: Optional[str] = None) -> dict:
    opts: dict = {
        "outtmpl":                       os.path.join(settings.DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "quiet":                         True,
        "noplaylist":                    True,
        "geo_bypass":                    True,
        "no_warnings":                   True,
        "overwrites":                    False,
        "nocheckcertificate":            True,
        "continuedl":                    True,
        "noprogress":                    True,
        "concurrent_fragment_downloads": 3,
        "http_chunk_size":               524288,
        "socket_timeout":                30,
        "retries":                       3,
        "fragment_retries":              3,
        "extractor_retries":             3,
        "sleep_interval_requests":       0,
        "extractor_args":                {"youtube": {"player_client": ["android", "web"]}},
    }
    if cookie:
        opts["cookiefile"] = cookie
    if video:
        h  = settings.VIDEO_MAX_HEIGHT
        hf = f"[height<={h}]" if h else ""
        opts["format"] = (
            f"bestvideo[ext=mp4]{hf}+bestaudio[ext=m4a]/"
            f"bestvideo{hf}+bestaudio/bestvideo+bestaudio/best"
        )
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
    else:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio/best"
        opts["postprocessors"] = []
    return opts


def _run_ydl(opts: dict, url: str, video_id: str, video: bool) -> Optional[str]:
    ydl = None
    try:
        os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
        ydl  = yt_dlp.YoutubeDL(opts)
        info = ydl.extract_info(url, download=True)
        if not info:
            return None
        time.sleep(0.2)
        return _locate_file(video_id, video=video)
    except (yt_dlp.utils.ExtractorError, yt_dlp.utils.DownloadError):
        raise
    except Exception as exc:
        logger.error(f"yt-dlp unexpected error for {video_id}: {exc}")
        return None
    finally:
        if ydl:
            try:
                ydl.close()
            except Exception:
                pass


def _sync_download(url: str, video_id: str, video: bool) -> Optional[str]:
    def try_phase(cookie: Optional[str], label: str) -> Optional[str]:
        try:
            return _run_ydl(_build_ydl_opts(video, cookie=cookie), url, video_id, video)
        except (yt_dlp.utils.ExtractorError, yt_dlp.utils.DownloadError) as exc:
            recovered = _locate_file(video_id, video=video)
            if recovered:
                logger.warning(f"[{label}] Recovered partial file for {video_id}")
                return recovered
            raise

    if settings.COOKIELESS_FIRST:
        try:
            result = try_phase(None, "cookieless")
            if result:
                return result
        except (yt_dlp.utils.ExtractorError, yt_dlp.utils.DownloadError) as exc:
            if _is_auth_error(exc):
                logger.info(f"Auth/age error for {video_id} — retrying with cookie")
            else:
                logger.warning(f"Cookieless failed for {video_id}: {exc} — trying with cookie")

    cookie = cookie_manager.get()
    if not cookie:
        if not settings.COOKIELESS_FIRST:
            try:
                return try_phase(None, "no-cookie-fallback")
            except Exception as exc:
                logger.error(f"Download failed for {video_id}: {exc}")
                return None
        logger.error(
            f"Download failed for {video_id} — no cookies available. "
            "Add Netscape .txt cookie files to cookies/ for age-restricted content."
        )
        return None

    try:
        result = try_phase(cookie, "with-cookie")
        if result:
            return result
        logger.error(f"Download failed for {video_id} in both phases")
        return None
    except Exception as exc:
        logger.error(f"Download failed with cookie for {video_id}: {exc}")
        return None


# --- Live streams ---

async def get_live_stream_url(video_id: str) -> Optional[str]:
    url = YT_BASE + video_id

    def _extract(cookie: Optional[str] = None) -> Optional[str]:
        opts: dict = {
            "quiet":          True,
            "no_warnings":    True,
            "format":         "bestaudio/best",
            "noplaylist":     True,
            "socket_timeout": 20,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        if cookie:
            opts["cookiefile"] = cookie
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            live_status = info.get("live_status", "")
            is_live = (
                info.get("is_live")
                or info.get("was_live")
                or live_status in ("is_live", "is_upcoming")
            )
            if not is_live:
                return None
            direct = info.get("url")
            if direct:
                return direct
            for fmt in info.get("formats", []):
                if fmt.get("acodec") != "none" and fmt.get("url"):
                    return fmt["url"]
            return info.get("manifest_url")

    try:
        result = await asyncio.wait_for(asyncio.to_thread(_extract, None), timeout=35)
        if result:
            return result
        cookie = cookie_manager.get()
        if cookie:
            result = await asyncio.wait_for(asyncio.to_thread(_extract, cookie), timeout=35)
        return result
    except asyncio.TimeoutError:
        logger.error(f"Live URL timed out for {video_id}")
        return None
    except Exception as exc:
        logger.error(f"Live URL error for {video_id}: {exc}")
        return None

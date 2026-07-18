# config.py — every tunable lives here, loaded from the environment.
# Copy sample.env to .env for local runs. On Railway/Render/etc. set these
# as dashboard environment variables instead.

import os
import tempfile

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _materialize_cookies(raw: str) -> str:
    """Write a Netscape-format cookies string (from an env var) to a
    private temp file yt-dlp can point `cookiefile` at.

    Opt-in only — YT_COOKIES stays unset for the default cookieless
    deployment. When set, this still lands the cookie *content* on disk
    for the lifetime of the process, so treat the env var itself as a
    secret (Railway/Render dashboard var, never committed to the repo).
    """
    fd, path = tempfile.mkstemp(prefix="ytc_", suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(raw)
    os.chmod(path, 0o600)
    return path


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str = "") -> list:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


class Settings:
    # --- Server ---
    # 7860 is the Gradio/HF-Spaces convention port — almost never already
    # bound by anything else on a fresh VPS (unlike 3000/5000/8000/8080,
    # which are the first thing most other stacks grab). Railway/Render
    # inject their own PORT at deploy time regardless, so this only matters
    # for bare-VPS/local runs.
    PORT: int = int(os.getenv("PORT", 7860))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    # Keep WORKERS=1 on a single small VPS/dyno — in-memory caches, locks and
    # semaphores below are per-process and are NOT shared across workers.
    WORKERS: int = int(os.getenv("WORKERS", 1))
    ENABLE_DOCS: bool = _bool("ENABLE_DOCS", "true")

    # --- Auth ---
    # Empty API_KEYS = fully open API (fine for a private VPS only you use).
    # Set one or more comma-separated keys to require them on every request,
    # either as header "X-API-Key: <key>" or query string "?api_key=<key>"
    # (the query form exists because ffmpeg/pytgcalls cannot send custom
    # headers when it opens a stream URL directly).
    API_KEYS: list = _list("API_KEYS")

    # --- yt-dlp / resolution ---
    # Client spoofing order for the first attempt. web_safari/web/android/ios
    # reliably return playable formats without cookies for normal videos.
    PLAYER_CLIENTS: list = _list(
        "PLAYER_CLIENTS", "web_safari,web,android,ios"
    )
    # Second-attempt clients used specifically when the first attempt fails
    # with an age-gate error. tv_embedded and android consistently bypass
    # YouTube's age verification without any cookie/login, because embedded
    # players are never shown the age-gate prompt in the first place.
    AGE_BYPASS_CLIENTS: list = _list(
        "AGE_BYPASS_CLIENTS", "tv_embedded,android"
    )
    # Country codes tried in order when a video reports as geo/region
    # blocked. geo_bypass spoofs the region via YouTube's own X-Goog
    # visitor-location signal — no VPN/proxy needed on the server itself.
    GEO_BYPASS_COUNTRIES: list = _list(
        "GEO_BYPASS_COUNTRIES", "US,GB,DE,CA,IN,NL,JP,SG"
    )
    # How long a resolved googlevideo URL is trusted before we re-resolve.
    # Google signs these for several hours; we stay well under that.
    URL_CACHE_TTL: int = int(os.getenv("URL_CACHE_TTL", 10800))  # 3h
    SEARCH_CACHE_TTL: int = int(os.getenv("SEARCH_CACHE_TTL", 600))  # 10m
    RESOLVE_TIMEOUT: int = int(os.getenv("RESOLVE_TIMEOUT", 20))
    # How many yt-dlp extractions may run at once. Extraction is mostly
    # network + a short-lived Node subprocess for the n-signature — cheap
    # enough on a low-spec VPS at this default.
    MAX_CONCURRENT_RESOLVES: int = int(os.getenv("MAX_CONCURRENT_RESOLVES", 8))

    # --- Streaming proxy ---
    HTTP_CHUNK_SIZE: int = int(os.getenv("HTTP_CHUNK_SIZE", 256 * 1024))
    UPSTREAM_TIMEOUT: int = int(os.getenv("UPSTREAM_TIMEOUT", 300))
    # A shared, persistent connection pool (see proxy.py) instead of opening
    # a fresh TLS connection per request — cuts latency and CPU per stream.
    POOL_MAX_CONNECTIONS: int = int(os.getenv("POOL_MAX_CONNECTIONS", 100))
    POOL_MAX_KEEPALIVE: int = int(os.getenv("POOL_MAX_KEEPALIVE", 20))

    # --- Video ---
    # "Default quality" — used by /play/video/hq when no ?height= override
    # is given. 720p is the bandwidth/quality sweet spot for voice-chat
    # playback; raise VIDEO_MAX_HEIGHT_CEILING if you want callers to be
    # able to request more via ?height=.
    VIDEO_DEFAULT_HEIGHT: int = int(os.getenv("VIDEO_DEFAULT_HEIGHT", 720))
    VIDEO_HQ_MAX_HEIGHT: int = int(os.getenv("VIDEO_HQ_MAX_HEIGHT", 720))
    VIDEO_SD_MAX_HEIGHT: int = int(os.getenv("VIDEO_SD_MAX_HEIGHT", 480))
    # Hard ceiling even if a caller passes ?height= higher than this.
    VIDEO_MAX_HEIGHT_CEILING: int = int(os.getenv("VIDEO_MAX_HEIGHT_CEILING", 1080))
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")

    # --- Optional cookie auth (opt-in, off by default) ---
    # Unset by default — the API stays fully cookieless unless you
    # explicitly set YT_COOKIES to a Netscape-format cookies.txt *content*
    # string (not a file path) as a Railway/Render dashboard env var. Used
    # only as an extra resolution attempt for videos that still fail after
    # the normal client-spoofing + age/geo-bypass ladder.
    YT_COOKIES_FILE: str | None = (
        _materialize_cookies(os.environ["YT_COOKIES"])
        if os.getenv("YT_COOKIES")
        else None
    )

    # --- Rate limiting (very small in-memory per-IP token bucket) ---
    # 0 disables it entirely (default — a single trusted bot doesn't need it).
    RATE_LIMIT_PER_MIN: int = int(os.getenv("RATE_LIMIT_PER_MIN", 0))

    # --- Branding ---
    WATERMARK: str = "BlacMusicAPI"
    DEV_URL: str = "https://t.me/blcqt"
    CHANNEL_URL: str = os.getenv("CHANNEL_URL", "https://t.me/TechTipsCode")


settings = Settings()

# config.py — all server settings, loaded from .env at startup
# Copy .env.example to .env and edit before running.

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Server
    PORT: int = int(os.getenv("PORT", 8000))
    # Keep WORKERS=1 on a single VPS — asyncio state (semaphores, caches) is not shared across workers
    WORKERS: int = int(os.getenv("WORKERS", 1))
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "true").lower() == "true"

    # Auth
    # Leave API_KEYS blank for an open API (good for private VPS).
    # Set comma-separated values to restrict access on public deployments.
    API_KEYS: list = [
        k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()
    ]

    # Downloads
    DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "downloads")
    # How long to keep each downloaded file on disk before auto-delete (seconds, default 2h)
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", 7200))
    # Max simultaneous yt-dlp downloads — tune this for your VPS (see README for table)
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 30))
    VIDEO_MAX_HEIGHT: int = int(os.getenv("VIDEO_MAX_HEIGHT", 1080))

    # Cookies
    COOKIES_DIR: str = os.getenv("COOKIES_DIR", "cookies")
    # When true: try without cookies first, fall back to a cookie only on 403/age errors
    COOKIELESS_FIRST: bool = os.getenv("COOKIELESS_FIRST", "true").lower() == "true"

    # Search cache (in-memory, per process)
    SEARCH_CACHE_TTL: int = int(os.getenv("SEARCH_CACHE_TTL", 600))  # 10 minutes

    # Branding — shown in every API response
    WATERMARK: str = "Blac"
    DEV_URL: str = "https://t.me/blcqt"
    CHANNEL_URL: str = "https://t.me/TechTipsCode"

    # Rate limiting (per IP, requests per minute — 0 disables)
    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", 0))


settings = Settings()

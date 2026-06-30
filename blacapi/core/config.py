import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    PORT: int = int(os.getenv("PORT", 8000))
    WORKERS: int = int(os.getenv("WORKERS", 1))
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "true").lower() == "true"

    API_KEYS: list = [
        k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()
    ]

    DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "downloads")
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", 7200))
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 30))
    VIDEO_MAX_HEIGHT: int = int(os.getenv("VIDEO_MAX_HEIGHT", 1080))

    COOKIES_DIR: str = os.getenv("COOKIES_DIR", "cookies")
    COOKIELESS_FIRST: bool = os.getenv("COOKIELESS_FIRST", "true").lower() == "true"

    SEARCH_CACHE_TTL: int = int(os.getenv("SEARCH_CACHE_TTL", 600))

    WATERMARK: str = "Blac"
    DEV_URL: str = "https://t.me/blcqt"
    CHANNEL_URL: str = "https://t.me/TechTipsCode"

    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", 0))


settings = Settings()

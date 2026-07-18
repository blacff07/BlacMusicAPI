import time

from fastapi import APIRouter

from blacapi.config import settings

router = APIRouter()
_started_at = time.monotonic()


@router.get("/")
async def root():
    # Deliberately static and fast — no yt-dlp/network work here. The bot
    # pings this on an interval purely to keep the host's dyno/container warm.
    return {
        "ok": True,
        "service": settings.WATERMARK,
        "status": "online",
        "uptime_sec": round(time.monotonic() - _started_at),
    }


@router.get("/health")
async def health():
    return {"ok": True, "status": "healthy"}

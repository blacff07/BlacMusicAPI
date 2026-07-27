import time
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from blacapi.config import settings
from blacapi.security import verify_api_key
from blacapi import stats as stats_module

router = APIRouter()
_started_at = time.monotonic()
_LANDING_PAGE = Path(__file__).resolve().parent.parent / "static" / "landing.html"


@router.get("/")
async def root():
    # Deliberately static and fast — no yt-dlp/network work here. The bot
    # pings this on an interval purely to keep the host's dyno/container warm.
    # Left untouched on purpose: hosting/uptime bots depend on this exact
    # JSON shape. The docs-style landing page lives at /home instead.
    return {
        "ok": True,
        "service": settings.WATERMARK,
        "status": "online",
        "uptime_sec": round(time.monotonic() - _started_at),
    }


@router.get("/home", include_in_schema=False)
async def landing():
    return FileResponse(_LANDING_PAGE, media_type="text/html")


@router.get("/health")
async def health():
    return {"ok": True, "status": "healthy"}


@router.get("/api/stats", dependencies=[Depends(verify_api_key)])
async def api_stats():
    # Gated behind the same API key as everything else (also a no-op if
    # API_KEYS is left empty, same as every other route).
    return {"ok": True, "stats": stats_module.snapshot()}

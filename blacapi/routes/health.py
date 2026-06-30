from fastapi import APIRouter

from blacapi.core.config import settings
from blacapi.utils.responses import ok

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    return ok({
        "message": "Blac Music API is running",
        "version": "1.0.0",
        "dev": settings.DEV_URL,
        "channel": settings.CHANNEL_URL,
        "docs": "/docs" if settings.ENABLE_DOCS else "disabled",
    })


@router.get("/ping")
async def ping():
    return {"ok": True, "ping": "pong"}

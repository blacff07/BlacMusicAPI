from fastapi import Header, HTTPException

from blacapi.core.config import settings


async def verify_api_key(x_api_key: str | None = Header(default=None)):
    if not settings.API_KEYS:
        return
    if not x_api_key or x_api_key not in settings.API_KEYS:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Set X-Api-Key header.",
        )

from fastapi import Header, HTTPException, Query

from blacapi.config import settings


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None),
) -> None:
    """Gate every route behind an optional API key.

    Accepted two ways on purpose:
      - header  X-API-Key: <key>   (normal HTTP clients, aiohttp/httpx JSON calls)
      - query   ?api_key=<key>     (ffmpeg/pytgcalls open stream URLs directly
                                     and cannot attach custom headers)

    If API_KEYS is left empty in the environment, the API is open and this
    check is a no-op — convenient for a private VPS only your own bot talks to.
    """
    if not settings.API_KEYS:
        return
    key = x_api_key or api_key
    if not key or key not in settings.API_KEYS:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Send X-API-Key header or ?api_key=",
        )

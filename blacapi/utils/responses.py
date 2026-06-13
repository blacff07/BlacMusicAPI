from blacapi.core.config import settings


def ok(data: dict) -> dict:
    """Standard success response — always includes Blac branding."""
    return {
        "ok": True,
        "powered_by": settings.WATERMARK,
        "dev": settings.DEV_URL,
        "channel": settings.CHANNEL_URL,
        **data,
    }


def err(message: str) -> dict:
    """Standard error response."""
    return {
        "ok": False,
        "error": message,
        "powered_by": settings.WATERMARK,
        "dev": settings.DEV_URL,
        "channel": settings.CHANNEL_URL,
    }

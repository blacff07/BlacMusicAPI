from blacapi.core.config import settings


def ok(data: dict) -> dict:
    return {
        "ok": True,
        "powered_by": settings.WATERMARK,
        "dev": settings.DEV_URL,
        "channel": settings.CHANNEL_URL,
        **data,
    }


def err(message: str) -> dict:
    return {
        "ok": False,
        "error": message,
        "powered_by": settings.WATERMARK,
        "dev": settings.DEV_URL,
        "channel": settings.CHANNEL_URL,
    }

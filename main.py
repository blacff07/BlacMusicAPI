import os
import sys

import uvicorn

from blacapi.app import create_app
from blacapi.config import settings
from blacapi.logger import logger

app = create_app()


def _public_url() -> str | None:
    """Best-effort public URL detection for common host platforms."""
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}"
    static = os.getenv("RAILWAY_STATIC_URL")
    if static:
        return static if static.startswith("http") else f"https://{static}"
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        return render_url
    return None


def _print_banner() -> None:
    local = f"http://127.0.0.1:{settings.PORT}"
    public = _public_url()
    lines = [
        f"{settings.WATERMARK} is running",
        f"Local   : {local}",
    ]
    if public:
        lines.append(f"Public  : {public}")
    if settings.ENABLE_DOCS:
        lines.append(f"Docs    : {local}/docs")
    lines.append(f"Health  : {local}/health")

    width = max(len(l) for l in lines) + 4
    print("┌" + "─" * width + "┐")
    for l in lines:
        print("│  " + l.ljust(width - 2) + "│")
    print("└" + "─" * width + "┘")


if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)

    logger.info(f"{settings.WATERMARK} starting on {settings.HOST}:{settings.PORT} ({settings.WORKERS} worker(s))")
    _print_banner()

    # uvloop is a drop-in faster event loop; not available on Windows.
    loop = "uvloop" if sys.platform != "win32" else "asyncio"

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        log_level="warning",
        access_log=False,
        loop=loop,
    )

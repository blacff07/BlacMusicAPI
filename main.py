import os
import sys
import uvicorn
from blacapi.app import create_app
from blacapi.core.config import settings
from blacapi.core.logger import logger

app = create_app()

if __name__ == "__main__":
    os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("cookies", exist_ok=True)

    logger.info(f"BlacMusicAPI starting on port {settings.PORT} with {settings.WORKERS} worker(s)")

    # uvloop is not available on Windows — fall back to the default asyncio loop
    loop = "uvloop" if sys.platform != "win32" else "asyncio"

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        workers=settings.WORKERS,
        log_level="warning",
        access_log=False,
        loop=loop,
    )

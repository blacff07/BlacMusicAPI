import asyncio
import os
import time

from blacapi.core.config import settings
from blacapi.core.logger import logger

_SKIP = frozenset({".part", ".ytdl", ".temp"})


async def _clean_loop():
    while True:
        await asyncio.sleep(900)  # run every 15 minutes
        try:
            now = time.time()
            removed = 0
            d = settings.DOWNLOAD_DIR
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                fpath = os.path.join(d, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext in _SKIP:
                    continue
                age = now - os.path.getmtime(fpath)
                if age > settings.CACHE_TTL:
                    try:
                        os.remove(fpath)
                        removed += 1
                    except OSError:
                        pass
            if removed:
                logger.info(f"Cleaner: removed {removed} expired file(s)")
        except Exception as exc:
            logger.error(f"Cleaner error: {exc}")


async def start_cleaner():
    os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
    asyncio.create_task(_clean_loop())

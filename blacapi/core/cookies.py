import os
import random

from blacapi.core.config import settings
from blacapi.core.logger import logger


class CookieManager:
    def __init__(self):
        self._cookies: list[str] = []
        self._loaded: bool = False
        self._warned: bool = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        d = settings.COOKIES_DIR
        if not os.path.isdir(d):
            return
        files = [
            os.path.join(d, f)
            for f in os.listdir(d)
            if f.endswith(".txt") and os.path.getsize(os.path.join(d, f)) > 50
        ]
        self._cookies = files
        if files:
            logger.info(f"Loaded {len(files)} cookie file(s) from {d}/")
        else:
            logger.info("No cookie files found — running cookieless (fine for most content)")

    def get(self) -> str | None:
        self._load()
        if not self._cookies:
            if not self._warned:
                self._warned = True
                logger.warning(
                    "No cookies available. Age-restricted content will fail. "
                    "Add Netscape .txt files to cookies/ to enable fallback."
                )
            return None
        return random.choice(self._cookies)

    @property
    def has_cookies(self) -> bool:
        self._load()
        return bool(self._cookies)

    def reload(self):
        self._loaded = False
        self._warned = False
        self._load()


cookie_manager = CookieManager()

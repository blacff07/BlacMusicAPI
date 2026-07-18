# cache.py — tiny in-process TTL cache + per-key asyncio locks.
#
# No Redis, no external dependency: a single-worker API process holds all of
# this in memory, which is exactly what a low-spec VPS wants (zero extra
# moving parts, zero extra RAM beyond a few thousand small dict entries).

import asyncio
import time
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl: int, max_size: int = 4000):
        self.ttl = ttl
        self.max_size = max_size
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        value, expires_at = item
        if expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if len(self._store) >= self.max_size:
            # Cheap eviction: drop the oldest ~10% by insertion order.
            for k in list(self._store.keys())[: max(1, self.max_size // 10)]:
                self._store.pop(k, None)
        self._store[key] = (value, time.monotonic() + (ttl if ttl is not None else self.ttl))

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def __len__(self) -> int:
        return len(self._store)


class KeyedLocks:
    """One asyncio.Lock per key, created lazily, swept periodically.

    Used so concurrent requests for the *same* video_id coalesce into a
    single yt-dlp resolution instead of hammering YouTube N times.
    """

    def __init__(self, sweep_after: int = 2000, sweep_batch: int = 500):
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta = asyncio.Lock()
        self._sweep_after = sweep_after
        self._sweep_batch = sweep_batch

    async def get(self, key: str) -> asyncio.Lock:
        async with self._meta:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            if len(self._locks) > self._sweep_after:
                idle = [k for k, v in list(self._locks.items()) if not v.locked()]
                for k in idle[: self._sweep_batch]:
                    self._locks.pop(k, None)
            return lock

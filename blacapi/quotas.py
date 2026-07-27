# quotas.py — optional per-API-key daily request caps.
#
# Same philosophy as cache.py/stats.py: plain in-memory dict, no Redis.
# Resets ~24h after process start (not calendar-day aligned) — fine for
# "cap how much someone else's bot can hit my API with the key I gave
# them", not meant to be a precise billing system.

import time
from collections import defaultdict

_DAY_SECONDS = 86400
_counts: dict[str, int] = defaultdict(int)
_window_start = time.monotonic()


def _maybe_reset() -> None:
    global _window_start
    now = time.monotonic()
    if now - _window_start >= _DAY_SECONDS:
        _counts.clear()
        _window_start = now


def check_and_increment(key: str, limit: int) -> bool:
    """Returns False (and does NOT increment) if key is already at limit."""
    _maybe_reset()
    if _counts[key] >= limit:
        return False
    _counts[key] += 1
    return True


def remaining(key: str, limit: int) -> int:
    _maybe_reset()
    return max(0, limit - _counts[key])

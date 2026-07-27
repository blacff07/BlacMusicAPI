# stats.py — tiny in-process counters for the /api/stats endpoint.
#
# Same philosophy as cache.py: no Redis, no external dependency, just plain
# dicts in the single worker process. Restarts reset it — this is meant for
# "is my cache actually working right now", not long-term analytics.

import time
from collections import Counter

_started_at = time.monotonic()

requests_total: Counter = Counter()
cache_hits: Counter = Counter()
cache_misses: Counter = Counter()
resolve_failures: Counter = Counter()


def note_request(path: str) -> None:
    requests_total[path] += 1


def note_cache(name: str, hit: bool) -> None:
    (cache_hits if hit else cache_misses)[name] += 1


def note_resolve_failure(video_id: str) -> None:
    resolve_failures["total"] += 1


def snapshot() -> dict:
    total_hits = sum(cache_hits.values())
    total_misses = sum(cache_misses.values())
    total = total_hits + total_misses
    names = set(cache_hits) | set(cache_misses)
    return {
        "uptime_sec": round(time.monotonic() - _started_at),
        "requests_total": sum(requests_total.values()),
        "requests_by_path": dict(requests_total.most_common(25)),
        "cache": {
            "hits": total_hits,
            "misses": total_misses,
            "hit_rate": round(total_hits / total, 3) if total else None,
            "by_cache": {
                name: {"hits": cache_hits.get(name, 0), "misses": cache_misses.get(name, 0)}
                for name in names
            },
        },
        "resolve_failures_total": sum(resolve_failures.values()),
    }

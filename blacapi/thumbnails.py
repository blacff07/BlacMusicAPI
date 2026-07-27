# thumbnails.py — GET /api/youtube/thumbnail?id=&size=
#
# No server-side resizing needed: i.ytimg.com already serves several fixed
# resolutions per video by filename. This just picks the right filename
# and proxies the bytes (with a fallback ladder, since maxresdefault.jpg
# doesn't exist for every video — some only go up to hqdefault).

import httpx

from blacapi.logger import logger
from blacapi.proxy import get_client

# name -> (filename, approx resolution)
_SIZES = {
    "small": "default.jpg",        # 120x90 — always exists
    "medium": "mqdefault.jpg",     # 320x180 — always exists
    "large": "hqdefault.jpg",      # 480x360 — always exists
    "xl": "sddefault.jpg",         # 640x480 — most videos
    "max": "maxresdefault.jpg",    # 1280x720 — only higher-res uploads
}
# Fallback order when a requested size 404s, ending on a filename that is
# always present for any valid video id.
_FALLBACK_ORDER = ["max", "xl", "large", "medium", "small"]

_THUMB_BASE = "https://i.ytimg.com/vi/{id}/{filename}"


async def fetch_thumbnail(video_id: str, size: str) -> tuple[bytes, str] | None:
    client = get_client()
    order = _FALLBACK_ORDER[_FALLBACK_ORDER.index(size):] if size in _FALLBACK_ORDER else _FALLBACK_ORDER
    for candidate in order:
        url = _THUMB_BASE.format(id=video_id, filename=_SIZES[candidate])
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.error(f"[thumbnails] request failed for {video_id}/{candidate}: {exc}")
            continue
        if resp.status_code == 200 and resp.content:
            return resp.content, resp.headers.get("content-type", "image/jpeg")
    return None

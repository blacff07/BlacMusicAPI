# schemas.py — normalized Pydantic response contract.
#
# Added additively: existing routes still return their original field
# names (duration_sec, channel, thumbnail, ...) so the existing Telegram
# bot integration doesn't break. Each metadata row also gets an extra
# `contract` object nested inside it with the standardized names below,
# for any client that wants a single consistent shape going forward.

from typing import Optional

from pydantic import BaseModel

from blacapi.config import settings


class TrackResponseContract(BaseModel):
    id: str
    title: str
    artist: str
    duration_seconds: int
    thumbnail_url: Optional[str] = None
    stream_proxy_url: str


def build_contract(row: dict, base_url: str = "") -> TrackResponseContract:
    """Build the normalized contract object from an existing row dict
    (as produced by metadata._row / _row_from_flat_entry / _row_from_ytdlp_info).
    """
    video_id = row.get("id", "")
    proxy_path = f"/api/youtube/play/audio?id={video_id}"
    return TrackResponseContract(
        id=video_id,
        title=row.get("title", ""),
        artist=row.get("channel", ""),
        duration_seconds=int(row.get("duration_sec") or 0),
        thumbnail_url=row.get("thumbnail") or None,
        stream_proxy_url=f"{base_url}{proxy_path}" if base_url else proxy_path,
    )

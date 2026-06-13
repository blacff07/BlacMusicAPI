from fastapi import APIRouter, Depends, HTTPException, Query

from blacapi.core.auth import verify_api_key
from blacapi.core.youtube import extract_video_id, get_live_stream_url, get_video_info
from blacapi.utils.responses import ok

router = APIRouter()


@router.get("/youtube", dependencies=[Depends(verify_api_key)])
async def video_info(
    id: str = Query(None, description="YouTube video ID (11 chars)"),
    url: str = Query(None, description="Full YouTube video URL"),
):
    """
    Get metadata for a YouTube video.
    Pass either `id` (video ID) or `url` (full YouTube URL).

    Returns: title, id, url, duration, duration_sec, thumbnail, channel, views.
    """
    if not id and not url:
        raise HTTPException(status_code=400, detail="Provide 'id' or 'url' query parameter.")
    video_id = id if id else extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video ID from provided URL.")
    info = await get_video_info(video_id)
    if not info:
        raise HTTPException(status_code=404, detail="Video not found or unavailable.")
    return ok({"video": info})


@router.get("/live", dependencies=[Depends(verify_api_key)])
async def live_stream_url(
    id: str = Query(None, description="YouTube live stream video ID"),
    url: str = Query(None, description="Full YouTube live stream URL"),
):
    """
    Get the direct HLS/audio stream URL for a YouTube live broadcast.
    Use this to stream live radio/events into a voice chat.
    """
    if not id and not url:
        raise HTTPException(status_code=400, detail="Provide 'id' or 'url' query parameter.")
    video_id = id if id else extract_video_id(url)
    stream_url = await get_live_stream_url(video_id)
    if not stream_url:
        raise HTTPException(
            status_code=404,
            detail="Not a live stream, or stream URL extraction failed.",
        )
    return ok({"stream_url": stream_url, "video_id": video_id})

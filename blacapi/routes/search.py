from fastapi import APIRouter, Depends, HTTPException, Query

from blacapi.core.auth import verify_api_key
from blacapi.core.youtube import get_playlist_ids, search_youtube
from blacapi.utils.responses import ok

router = APIRouter()


@router.get("/youtube", dependencies=[Depends(verify_api_key)])
async def search_yt(
    q: str = Query(..., description="Search query or YouTube URL"),
    limit: int = Query(5, ge=1, le=20, description="Number of results (max 20)"),
):
    """
    Search YouTube. Returns a list of track objects.

    Each result includes: title, id, url, duration, duration_sec, thumbnail, channel, views.
    """
    results = await search_youtube(q, limit=limit)
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this query.")
    return ok({"results": results, "count": len(results)})


@router.get("/playlist", dependencies=[Depends(verify_api_key)])
async def search_playlist(
    url: str = Query(..., description="YouTube playlist URL"),
    limit: int = Query(50, ge=1, le=200, description="Max tracks to return"),
):
    """
    Fetch video IDs from a YouTube playlist.
    Returns a list of video ID strings.
    """
    ids = await get_playlist_ids(url, limit=limit)
    if not ids:
        raise HTTPException(status_code=404, detail="Playlist not found or is empty.")
    return ok({"video_ids": ids, "count": len(ids)})

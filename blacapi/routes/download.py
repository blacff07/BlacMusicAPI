import os
import shutil
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from blacapi.core.auth import verify_api_key
from blacapi.core.youtube import download_track, extract_video_id
from blacapi.utils.responses import ok

router = APIRouter()

_CONTENT_TYPES = {
    ".mp4":  "video/mp4",
    ".mkv":  "video/x-matroska",
    ".webm": "video/webm",
    ".m4a":  "audio/mp4",
    ".mp3":  "audio/mpeg",
    ".opus": "audio/ogg",
    ".ogg":  "audio/ogg",
    ".flac": "audio/flac",
}


def _media_type(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _delete_file(path: str):
    """Background cleanup — deletes the temp copy after streaming finishes."""
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass


@router.get("", dependencies=[Depends(verify_api_key)])
async def download_stream(
    background_tasks: BackgroundTasks,
    url: str = Query(None, description="Full YouTube URL"),
    id: str = Query(None, description="YouTube video ID"),
    type: str = Query("audio", description="'audio' for /play  |  'video' for /vplay"),
):
    """
    Stream an audio or video file.

    type=audio  best quality audio (m4a/opus) — use for /play
    type=video  best quality video+audio (mp4) — use for /vplay

    Files are cached. Repeat requests for the same ID are served instantly.
    """
    if not url and not id:
        raise HTTPException(status_code=400, detail="Provide 'id' or 'url' query parameter.")

    video_id = id if id else extract_video_id(url)
    if not video_id or len(video_id) < 5:
        raise HTTPException(status_code=400, detail="Invalid video ID or URL.")

    is_video = type.lower() in ("video", "vplay", "v")
    filepath = await download_track(video_id, video=is_video)

    if not filepath or not os.path.isfile(filepath):
        raise HTTPException(
            status_code=500,
            detail=(
                "Download failed. Video may be age-restricted, private, or unavailable. "
                "Add Netscape .txt cookie files to cookies/ for age-restricted content."
            ),
        )

    # Stream from a temp copy so the cleaner can't delete the source
    # mid-transfer. BackgroundTasks deletes the copy after the response finishes.
    ext = os.path.splitext(filepath)[1].lower()
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=ext,
        dir=os.path.dirname(filepath),
    )
    try:
        shutil.copy2(filepath, tmp.name)
        tmp.close()
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to prepare file for streaming.")

    background_tasks.add_task(_delete_file, tmp.name)

    return FileResponse(
        path=tmp.name,
        media_type=_media_type(filepath),
        filename=f"{video_id}{ext}",
        headers={
            "X-Powered-By": "BlacMusicAPI",
            "X-Dev":        "https://t.me/blcqt",
            "X-Channel":    "https://t.me/TechTipsCode",
            "X-Video-ID":   video_id,
            "X-Media-Type": "video" if is_video else "audio",
        },
    )


@router.get("/path", dependencies=[Depends(verify_api_key)])
async def download_path(
    url: str = Query(None, description="Full YouTube URL"),
    id: str = Query(None, description="YouTube video ID"),
    type: str = Query("audio", description="'audio' or 'video'"),
):
    """
    Returns the local file path instead of streaming the file.
    Use this when your bot runs on the same VPS as the API.
    Pass the filepath directly to AudioPiped() or VideoPiped().
    """
    if not url and not id:
        raise HTTPException(status_code=400, detail="Provide 'id' or 'url' query parameter.")

    video_id = id if id else extract_video_id(url)
    if not video_id or len(video_id) < 5:
        raise HTTPException(status_code=400, detail="Invalid video ID or URL.")

    is_video = type.lower() in ("video", "vplay", "v")
    filepath = await download_track(video_id, video=is_video)

    if not filepath or not os.path.isfile(filepath):
        raise HTTPException(status_code=500, detail="Download failed.")

    return ok({
        "video_id":   video_id,
        "filepath":   os.path.abspath(filepath),
        "type":       "video" if is_video else "audio",
        "size_bytes": os.path.getsize(filepath),
        "filename":   os.path.basename(filepath),
    })

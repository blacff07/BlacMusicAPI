# routes/youtube.py — the surface a Telegram music bot actually talks to.
#
# Byte-proxy endpoints (audio/video bytes streamed straight through):
#   GET /api/youtube/play/audio                    -> audio bytes, Range-aware
#   GET /api/youtube/play/video/hq?height=<optional> -> muxed video, default 720p
#   GET /api/youtube/play/video?height=<optional>    -> muxed video, default 480p (lighter fallback)
#
# `height` is optional on both video routes and lets a caller trade quality
# for bandwidth per-request; omit it to use the server's configured default.
#
# JSON metadata endpoints (signed googlevideo URLs — IP-locked to *this*
# server's egress, kept only as a fallback tier for self-hosted deployments
# where the bot happens to share that egress; the /play/* routes above are
# the recommended primary path for any deployment):
#   GET /api/youtube/audio               -> {success, audio: {audio_streams: [...]}}
#   GET /api/youtube/stream              -> {success, stream: {url}}
#
# Generic metadata (handy for any bot, not just this one):
#   GET /api/youtube/search?q=
#   GET /api/youtube/info?id=
#   GET /api/youtube/playlist?url=

import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from blacapi import download as download_module
from blacapi import metadata, resolver, thumbnails, webhook
from blacapi.config import settings
from blacapi.proxy import stream_result
from blacapi.schemas import build_contract
from blacapi.security import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _vid(id: str) -> str:
    video_id = resolver.extract_video_id(id)
    if not video_id or len(video_id) < 8:
        raise HTTPException(status_code=400, detail="Invalid or missing video id")
    return video_id


# --- Byte-proxy streaming (primary path) ---------------------------------

async def _play_audio(request: Request, id: str = Query(...)):
    video_id = _vid(id)

    async def _resolve(force: bool):
        return await resolver.resolve_audio(video_id, force=force)

    def _invalidate():
        resolver.invalidate_audio(video_id)

    return await stream_result(request, video_id, _resolve, _invalidate)


router.add_api_route("/play/audio", _play_audio, methods=["GET"], name="play_audio")
router.add_api_route("/play/audio", _play_audio, methods=["HEAD"], name="play_audio_head", include_in_schema=False)


async def _play_video_hq(request: Request, id: str = Query(...), height: int | None = Query(default=None, ge=144, le=4320)):
    video_id = _vid(id)
    max_h = min(height, settings.VIDEO_MAX_HEIGHT_CEILING) if height else settings.VIDEO_HQ_MAX_HEIGHT

    async def _resolve(force: bool):
        return await resolver.resolve_video(video_id, max_h, force=force)

    def _invalidate():
        resolver.invalidate_video(video_id, max_h)

    return await stream_result(request, video_id, _resolve, _invalidate)


router.add_api_route("/play/video/hq", _play_video_hq, methods=["GET"], name="play_video_hq")
router.add_api_route("/play/video/hq", _play_video_hq, methods=["HEAD"], name="play_video_hq_head", include_in_schema=False)


async def _play_video(request: Request, id: str = Query(...), height: int | None = Query(default=None, ge=144, le=4320)):
    video_id = _vid(id)
    max_h = min(height, settings.VIDEO_MAX_HEIGHT_CEILING) if height else settings.VIDEO_SD_MAX_HEIGHT

    async def _resolve(force: bool):
        return await resolver.resolve_video(video_id, max_h, force=force)

    def _invalidate():
        resolver.invalidate_video(video_id, max_h)

    return await stream_result(request, video_id, _resolve, _invalidate)


router.add_api_route("/play/video", _play_video, methods=["GET"], name="play_video")
router.add_api_route("/play/video", _play_video, methods=["HEAD"], name="play_video_head", include_in_schema=False)


# --- JSON metadata (fallback tier) ----------------------------------------

_VALID_QUALITIES = {"low", "medium", "high"}


@router.get("/audio")
async def audio_formats(id: str = Query(...), quality: str | None = Query(None)):
    video_id = _vid(id)
    if quality is not None and quality not in _VALID_QUALITIES:
        raise HTTPException(status_code=422, detail="quality must be one of: low, medium, high")
    # resolver.list_audio_formats raises VideoNotFoundError (404) itself if
    # nothing playable is found — no need to re-check here.
    streams = await resolver.list_audio_formats(video_id, quality=quality)
    return {"success": True, "audio": {"id": video_id, "audio_streams": streams}}


@router.get("/stream")
async def stream_json(id: str = Query(...), with_fallbacks: bool = Query(False)):
    video_id = _vid(id)
    result = await resolver.resolve_video(video_id, settings.VIDEO_SD_MAX_HEIGHT)
    if result.needs_mux:
        raise HTTPException(
            status_code=404,
            detail="No single-file stream URL available for this video (only split video/audio streams exist — use /play/video instead, which muxes them on the fly)",
        )
    payload = {
        "success": True,
        "stream": {"id": video_id, "url": result.url, "format_id": result.format_id, "ext": result.ext},
    }
    if with_fallbacks:
        # Opt-in only — resolving extra qualities costs extra yt-dlp calls,
        # so normal requests don't pay for it unless asked.
        payload["stream"]["qualities"] = await resolver.list_video_qualities(video_id, [480, 360, 240])
    return payload


# --- Generic metadata -------------------------------------------------------

@router.get("/search")
async def search(q: str = Query(...), limit: int = Query(5, ge=1, le=20)):
    results = await metadata.search(q, limit)
    for r in results:
        r["contract"] = build_contract(r)
    return {"success": True, "results": results}


@router.get("/info")
async def info(id: str = Query(...)):
    video_id = _vid(id)
    data = await metadata.get_info(video_id)
    if not data:
        raise HTTPException(status_code=404, detail="Video not found")
    data["contract"] = build_contract(data)
    return {"success": True, "info": data}


_MAX_BATCH_IDS = 50


@router.get("/info/batch")
async def info_batch(ids: str = Query(..., description="Comma-separated video ids or URLs")):
    raw = [v.strip() for v in ids.split(",") if v.strip()]
    if not raw:
        raise HTTPException(status_code=400, detail="No ids provided")
    if len(raw) > _MAX_BATCH_IDS:
        raise HTTPException(status_code=422, detail=f"Too many ids — max {_MAX_BATCH_IDS} per request")
    video_ids = [_vid(v) for v in raw]
    rows = await metadata.get_info_batch(video_ids)
    for r in rows:
        if "error" not in r:
            r["contract"] = build_contract(r)
    return {"success": True, "results": rows}


@router.get("/playlist")
async def playlist(url: str = Query(...), limit: int = Query(50, ge=1, le=200)):
    results = await metadata.get_playlist(url, limit)
    for r in results:
        r["contract"] = build_contract(r)
    webhook.notify_playlist_processed(url, limit, len(results))
    return {"success": True, "results": results}


@router.get("/related")
async def related(id: str = Query(...), limit: int = Query(10, ge=1, le=20)):
    """Best-effort recommendations. yt-dlp's related_videos field is not
    reliably populated by YouTube anymore, so this falls back to a plain
    search seeded from the source video's own title when it comes back
    empty — the results are approximate ("more like this"), not a true
    watch-next graph."""
    video_id = _vid(id)
    rows = await metadata.get_related(video_id, limit)
    for r in rows:
        r["contract"] = build_contract(r)
    return {"success": True, "results": rows}


# --- Thumbnails ---------------------------------------------------------

_THUMB_SIZES = {"small", "medium", "large", "xl", "max"}


@router.get("/thumbnail")
async def thumbnail(id: str = Query(...), size: str = Query("large")):
    """Proxies YouTube's own fixed-resolution thumbnail images — no
    server-side resizing needed, YouTube already serves several sizes per
    video. Falls back to progressively smaller sizes if the requested one
    doesn't exist for this video (maxresdefault isn't generated for every
    upload)."""
    video_id = _vid(id)
    if size not in _THUMB_SIZES:
        raise HTTPException(status_code=422, detail=f"size must be one of: {', '.join(sorted(_THUMB_SIZES))}")
    found = await thumbnails.fetch_thumbnail(video_id, size)
    if not found:
        raise HTTPException(status_code=404, detail="No thumbnail available for this video")
    content, content_type = found
    return Response(content=content, media_type=content_type)


# --- One-shot file download (vs. the live /play/* proxy) -----------------

_VALID_DOWNLOAD_TYPES = {"audio", "video"}


def _cleanup_temp_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@router.get("/download")
async def download(
    id: str = Query(...),
    type: str = Query("audio", description="audio or video"),
    height: int = Query(720, ge=144, le=4320, description="Only used when type=video"),
):
    """Returns a fully-materialized file (Content-Disposition: attachment)
    instead of a live proxy stream — for bots that need a real file on
    hand (e.g. re-uploading to Telegram, which wants a known byte length
    upfront) rather than piping playback through /play/audio or
    /play/video. Slower than those routes since it waits for the whole
    file before responding; use them instead for actual playback."""
    if type not in _VALID_DOWNLOAD_TYPES:
        raise HTTPException(status_code=422, detail="type must be one of: audio, video")
    video_id = _vid(id)
    filepath, media_type = await download_module.build_download(video_id, type, height)
    ext = filepath.rsplit(".", 1)[-1]
    return FileResponse(
        filepath,
        media_type=media_type,
        filename=f"{video_id}.{ext}",
        background=BackgroundTask(_cleanup_temp_file, filepath),
    )

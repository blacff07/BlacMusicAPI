# download.py — GET /api/youtube/download: a fully-materialized file on
# disk, not a live stream. For bots that want a finished file (e.g. to
# re-upload to Telegram, which needs a real file/byte-length upfront)
# rather than proxying live playback like /play/audio and /play/video do.
#
# Reuses the exact same resolver + ffmpeg logic as the live proxy (direct
# URL / DASH mux / HLS remux, same aac_adtstoasc fix) — the only
# difference is ffmpeg writes to a real file path instead of piping to
# stdout, and this waits for the whole thing to finish before returning.

import asyncio
import os
import tempfile

from blacapi.config import settings
from blacapi.errors import ResolutionError, VideoNotFoundError
from blacapi.logger import logger
from blacapi.proxy import _BROWSER_HEADERS_ARGS
from blacapi.resolver import StreamResult, resolve_audio, resolve_video


def _cmd_for(result: StreamResult, out_path: str) -> list:
    base = [settings.FFMPEG_PATH, "-y", "-loglevel", "warning"]
    if result.needs_mux:
        return [
            *base,
            *_BROWSER_HEADERS_ARGS, "-i", result.url,
            *_BROWSER_HEADERS_ARGS, "-i", result.audio_url,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c", "copy", out_path,
        ]
    if result.is_hls:
        if result.kind == "audio":
            return [
                *base, *_BROWSER_HEADERS_ARGS, "-i", result.url,
                "-vn", "-c:a", "copy", "-bsf:a", "aac_adtstoasc", out_path,
            ]
        return [
            *base, *_BROWSER_HEADERS_ARGS, "-i", result.url,
            "-c", "copy", "-bsf:a", "aac_adtstoasc", out_path,
        ]
    # Direct DASH/progressive URL — ffmpeg can pull straight from http(s);
    # still send browser headers since some CDN edges check them.
    return [*base, *_BROWSER_HEADERS_ARGS, "-i", result.url, "-c", "copy", out_path]


async def _run_ffmpeg_to_file(cmd: list) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        raise ResolutionError(
            f"ffmpeg was not found on the server at '{settings.FFMPEG_PATH}'.", status_code=502
        )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        text = stderr.decode(errors="replace")[-2000:] if stderr else "(no stderr output)"
        logger.error(f"[download] ffmpeg exited code={proc.returncode}: {text}")
        raise ResolutionError(f"Failed to build downloadable file (ffmpeg exit {proc.returncode})", status_code=502)


async def build_download(video_id: str, kind: str, height: int = 720) -> tuple[str, str]:
    """Resolves + fully downloads audio or video to a temp file.

    Returns (filepath, media_type). The caller (routes/youtube.py) is
    responsible for deleting filepath once the response finishes sending
    — it's attached as a BackgroundTask there rather than cleaned up here,
    since the file must still exist while FileResponse streams it out.
    """
    if kind == "audio":
        result = await resolve_audio(video_id)
        ext, media_type = "m4a", "audio/mp4"
    else:
        result = await resolve_video(video_id, height)
        ext, media_type = "mp4", "video/mp4"

    if not result:
        raise VideoNotFoundError(f"Could not resolve a playable stream for {video_id}")

    fd, out_path = tempfile.mkstemp(prefix="blacmusicapi_dl_", suffix=f".{ext}")
    os.close(fd)
    os.remove(out_path)  # ffmpeg creates it fresh; an empty pre-existing file can confuse some muxers

    cmd = _cmd_for(result, out_path)
    try:
        await _run_ffmpeg_to_file(cmd)
    except Exception:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise

    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise ResolutionError("Downloaded file came back empty or too small", status_code=502)

    return out_path, media_type

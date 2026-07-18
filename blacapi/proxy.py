# proxy.py — turns a resolved StreamResult into an HTTP StreamingResponse.
#
# Why proxy bytes instead of redirecting/returning the signed googlevideo URL?
# Signed googlevideo URLs are locked to the IP that requested them. If this
# API handed the URL to a bot running on a *different* VPS, YouTube 403s it.
# By fetching the bytes here and streaming them onward, the bot never talks
# to googlevideo directly — only to us — so it works from any bot host,
# any region, with zero cookies.
#
# A single shared, persistent httpx.AsyncClient with connection pooling is
# used for every request instead of opening a new client (new TLS handshake)
# per stream — this is a meaningful chunk of the "faster responses" budget,
# especially for short probe requests.

import asyncio
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from blacapi.config import settings
from blacapi.errors import DependencyMissingError, ResolutionError, VideoNotFoundError
from blacapi.logger import logger
from blacapi.resolver import StreamResult

_PASSTHROUGH_HEADERS = ("content-length", "content-range", "accept-ranges")

_AUDIO_CONTENT_TYPES = {
    "m4a": "audio/mp4",
    "webm": "audio/webm",
    "opus": "audio/webm",
    "mp3": "audio/mpeg",
}

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Lazily create the single shared upstream HTTP client for the process."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.UPSTREAM_TIMEOUT, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=settings.POOL_MAX_CONNECTIONS,
                max_keepalive_connections=settings.POOL_MAX_KEEPALIVE,
            ),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _content_type_for(result: StreamResult) -> str:
    if result.kind == "video":
        return "video/mp4"
    return _AUDIO_CONTENT_TYPES.get(result.ext, "audio/mpeg")


async def stream_result(
    request: Request,
    video_id: str,
    resolve: Callable[[bool], Awaitable[Optional[StreamResult]]],
    invalidate: Callable[[], None],
) -> Response:
    """Resolve + proxy a stream. `resolve(force)` re-resolves bypassing cache.
    `resolve` normally raises a classified ResolutionError on failure (see
    errors.py) rather than returning None — the None check below is a
    defensive fallback only, in case a caller returns it directly.

    HEAD requests (e.g. `curl -I` for a quick smoke-test) are answered
    without pulling any media bytes — only GET triggers the actual proxy.
    """
    result = await resolve(False)
    if not result:
        raise VideoNotFoundError(f"Could not resolve a playable stream for {video_id}")

    content_type = _content_type_for(result)

    if request.method == "HEAD":
        if result.needs_mux or result.is_hls:
            return Response(status_code=200, media_type=content_type)
        headers = await _peek_headers(result.url)
        return Response(status_code=200, media_type=content_type, headers=headers)

    if result.needs_mux:
        return await _mux_stream(result)

    if result.is_hls:
        return await _remux_hls_stream(result)

    range_header = request.headers.get("range")
    upstream = await _open_upstream(result.url, range_header)

    if upstream.status_code in (401, 403, 404, 410):
        # Cached URL expired (googlevideo signatures are time-limited) — drop
        # it and resolve exactly once more before giving up.
        await upstream.aclose()
        invalidate()
        result = await resolve(True)
        if not result:
            raise VideoNotFoundError(f"Stream expired and could not be re-resolved for {video_id}")
        if result.needs_mux:
            return await _mux_stream(result)
        if result.is_hls:
            return await _remux_hls_stream(result)
        upstream = await _open_upstream(result.url, range_header)

    if upstream.status_code >= 400:
        body_preview = (await upstream.aread())[:200]
        await upstream.aclose()
        logger.error(f"[proxy] upstream {upstream.status_code} for {video_id}: {body_preview!r}")
        raise ResolutionError(
            f"Upstream video source rejected the request (HTTP {upstream.status_code})", status_code=502
        )

    headers = {}
    for h in _PASSTHROUGH_HEADERS:
        if h in upstream.headers:
            headers[h] = upstream.headers[h]

    return StreamingResponse(
        _iter_upstream(upstream),
        status_code=upstream.status_code,
        media_type=content_type,
        headers=headers,
    )


async def _peek_headers(url: str) -> dict:
    """A cheap 1-byte range probe — enough to confirm the source is alive and
    surface accept-ranges/content-range without downloading anything."""
    client = get_client()
    try:
        resp = await client.get(url, headers={"Range": "bytes=0-0"})
        headers = {h: resp.headers[h] for h in _PASSTHROUGH_HEADERS if h in resp.headers}
        await resp.aclose()
        return headers
    except Exception as exc:
        logger.warning(f"[proxy] HEAD probe failed: {exc}")
        return {}


async def _open_upstream(url: str, range_header: Optional[str]) -> httpx.Response:
    client = get_client()
    req_headers = {"Range": range_header} if range_header else {}
    req = client.build_request("GET", url, headers=req_headers)
    try:
        return await client.send(req, stream=True)
    except Exception as exc:
        logger.error(f"[proxy] failed to reach upstream source: {exc}")
        raise ResolutionError(f"Failed to reach video source: {exc}", status_code=502)


async def _iter_upstream(upstream: httpx.Response):
    try:
        async for chunk in upstream.aiter_bytes(settings.HTTP_CHUNK_SIZE):
            yield chunk
    finally:
        await upstream.aclose()


# Some googlevideo chunk hosts (particularly for HLS segments) expect a
# browser-like User-Agent/Referer on requests; ffmpeg's default identifies
# itself as "Lavf/..." which can get segment fetches quietly rejected mid-
# stream after the manifest itself loads fine. These are harmless to send
# even when not required.
_BROWSER_HEADERS_ARGS = [
    "-user_agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "-headers", "Referer: https://www.youtube.com/\r\n",
]


async def _mux_stream(result: StreamResult) -> StreamingResponse:
    """Stream-copy mux of separate video+audio DASH URLs via ffmpeg.

    No re-encoding happens (-c copy), so CPU cost is negligible — this is
    fine even on a 1-vCPU VPS. Output uses fragmented MP4 so playback can
    start before the whole file exists (there's no seekable moov atom to
    wait for).
    """
    cmd = [
        settings.FFMPEG_PATH, "-loglevel", "warning",
        *_BROWSER_HEADERS_ARGS, "-i", result.url,
        *_BROWSER_HEADERS_ARGS, "-i", result.audio_url,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c", "copy",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "pipe:1",
    ]
    return await _run_ffmpeg_stream(cmd, "video/mp4")


async def _remux_hls_stream(result: StreamResult) -> StreamingResponse:
    """Remux an HLS (m3u8) manifest into a normal continuous stream.

    Used when YouTube offers no direct/DASH format at all for a video (seen
    on some datacenter IPs) — ffmpeg fetches and reassembles the HLS
    segments itself, so this still needs no cookies and no browser. Audio
    requests drop the video track; video requests keep both.
    """
    if result.kind == "audio":
        cmd = [
            settings.FFMPEG_PATH, "-loglevel", "warning",
            *_BROWSER_HEADERS_ARGS, "-i", result.url,
            "-vn", "-c:a", "copy",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-f", "mp4", "pipe:1",
        ]
        media_type = "audio/mp4"
    else:
        cmd = [
            settings.FFMPEG_PATH, "-loglevel", "warning",
            *_BROWSER_HEADERS_ARGS, "-i", result.url,
            "-c", "copy",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-f", "mp4", "pipe:1",
        ]
        media_type = "video/mp4"
    return await _run_ffmpeg_stream(cmd, media_type)


async def _run_ffmpeg_stream(cmd: list, media_type: str) -> StreamingResponse:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error(f"[proxy] ffmpeg binary not found at '{settings.FFMPEG_PATH}'")
        raise DependencyMissingError(
            f"ffmpeg was not found on the server at '{settings.FFMPEG_PATH}'. "
            "It's required for this stream."
        )

    bytes_sent = 0

    async def _gen():
        nonlocal bytes_sent
        try:
            while True:
                chunk = await proc.stdout.read(settings.HTTP_CHUNK_SIZE)
                if not chunk:
                    break
                bytes_sent += len(chunk)
                yield chunk
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            await proc.wait()
            # Surface ffmpeg's real error instead of silently discarding it —
            # this is what tells us *why* a stream came back truncated.
            try:
                stderr_data = await proc.stderr.read()
            except Exception:
                stderr_data = b""
            if proc.returncode not in (0, None) or bytes_sent < 4096:
                text = stderr_data.decode(errors="replace")[-2000:] if stderr_data else "(no stderr output)"
                logger.error(
                    f"[proxy] ffmpeg exited code={proc.returncode} after {bytes_sent} bytes: {text}"
                )

    return StreamingResponse(_gen(), media_type=media_type)

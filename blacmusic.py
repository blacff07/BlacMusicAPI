# blacmusic.py — Blac Music API client SDK
#
# Drop this single file into your music bot project.
#
# Quick start:
#   from blacmusic import BlacAPI
#
#   api = BlacAPI(base_url="http://localhost:8000", api_key="YOUR_KEY")
#
#   results  = await api.search("Alan Walker Faded")
#   track    = results[0]
#   # track keys: title, id, url, duration, duration_sec, thumbnail, channel, views
#
#   filepath = await api.download_audio(track["id"])   # for /play
#   filepath = await api.download_video(track["id"])   # for /vplay
#   info     = await api.get_info("dQw4w9WgXcQ")
#   stream   = await api.get_live_url("dQw4w9WgXcQ")   # for live streams
#   ids      = await api.get_playlist("https://youtube.com/playlist?list=PL...")
#
# Powered by Blac — https://t.me/blcqt | https://t.me/TechTipsCode

import os
import asyncio
import aiohttp
from typing import Optional

__version__ = "1.0.0"
__author__  = "Blac"
__dev__     = "https://t.me/blcqt"
__channel__ = "https://t.me/TechTipsCode"


class BlacAPIError(Exception):
    """Raised when the Blac Music API returns an error or the request fails."""
    pass


class BlacAPI:
    """
    Async client for the Blac Music API.

    Parameters:
        base_url     - URL of your running API (e.g. "http://localhost:8000")
        api_key      - API key if you set API_KEYS in .env. Leave None for open deployments.
        download_dir - Local directory to cache downloaded files.
        timeout      - Timeout in seconds for download requests.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        download_dir: str = "downloads",
        timeout: int = 300,
    ):
        self.base_url     = base_url.rstrip("/")
        self.api_key      = api_key
        self.download_dir = download_dir
        self.timeout      = timeout
        os.makedirs(self.download_dir, exist_ok=True)

    @property
    def _headers(self) -> dict:
        h: dict = {}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    async def _get(self, path: str, params: dict, timeout: int = 30) -> dict:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            try:
                async with session.get(
                    f"{self.base_url}{path}",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    try:
                        data = await resp.json()
                    except Exception:
                        text = await resp.text()
                        raise BlacAPIError(f"Non-JSON response ({resp.status}): {text[:200]}")
                    if not data.get("ok"):
                        raise BlacAPIError(data.get("error", f"API error {resp.status}"))
                    return data
            except aiohttp.ClientConnectorError:
                raise BlacAPIError(
                    f"Cannot connect to API at {self.base_url}. "
                    "Is the server running?"
                )
            except asyncio.TimeoutError:
                raise BlacAPIError(f"Request to {path} timed out after {timeout}s")

    # --- Search ---

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """
        Search YouTube. Returns a list of track dicts.
        Each dict: title, id, url, duration, duration_sec, thumbnail, channel, views.
        """
        data = await self._get("/search/youtube", {"q": query, "limit": limit})
        return data["results"]

    async def get_playlist(self, playlist_url: str, limit: int = 50) -> list[str]:
        """Fetch video IDs from a YouTube playlist. Returns a list of ID strings."""
        data = await self._get("/search/playlist", {"url": playlist_url, "limit": limit})
        return data["video_ids"]

    # --- Info ---

    async def get_info(self, video_id: str) -> dict:
        """Get metadata for a video ID: title, id, url, duration, duration_sec, thumbnail, channel, views."""
        data = await self._get("/info/youtube", {"id": video_id})
        return data["video"]

    async def get_live_url(self, video_id: str) -> str:
        """Get the direct HLS/audio stream URL for a YouTube live broadcast."""
        data = await self._get("/info/live", {"id": video_id}, timeout=45)
        return data["stream_url"]

    # --- Download ---

    async def download_audio(self, video_id: str) -> str:
        """
        Download audio for /play. Returns the local filepath.
        Cached — repeated calls for the same ID return the existing file instantly.
        """
        return await self._download(video_id, "audio")

    async def download_video(self, video_id: str) -> str:
        """
        Download video for /vplay. Returns the local filepath.
        Cached — repeated calls for the same ID return the existing file instantly.
        """
        return await self._download(video_id, "video")

    async def _download(self, video_id: str, dtype: str) -> str:
        # Check local disk cache first — avoids a round-trip to the API
        audio_exts = [".m4a", ".mp3", ".webm", ".opus", ".ogg", ".flac"]
        video_exts = [".mp4", ".mkv", ".webm"]
        exts = video_exts if dtype == "video" else audio_exts

        for ext in exts:
            p = os.path.join(self.download_dir, f"{video_id}{ext}")
            if os.path.isfile(p) and os.path.getsize(p) > 1024:
                return p

        # Download to a temp file first, then rename on success.
        # This prevents a corrupt partial file being cached if the connection drops.
        temp_path = os.path.join(self.download_dir, f"{video_id}.tmp")

        async with aiohttp.ClientSession(headers=self._headers) as session:
            try:
                async with session.get(
                    f"{self.base_url}/download",
                    params={"id": video_id, "type": dtype},
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise BlacAPIError(f"Download failed ({resp.status}): {body}")

                    ext = self._guess_ext(
                        resp.headers.get("content-type", ""),
                        resp.headers.get("content-disposition", ""),
                        dtype,
                    )
                    final_path = os.path.join(self.download_dir, f"{video_id}{ext}")

                    try:
                        with open(temp_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(131072):
                                f.write(chunk)
                    except Exception as exc:
                        # Clean up partial temp file
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        raise BlacAPIError(f"Write error during download: {exc}")

            except aiohttp.ClientConnectorError:
                raise BlacAPIError(f"Cannot connect to API at {self.base_url}")
            except asyncio.TimeoutError:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise BlacAPIError(f"Download timed out after {self.timeout}s for {video_id}")

        if not os.path.isfile(temp_path) or os.path.getsize(temp_path) < 1024:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise BlacAPIError(f"Downloaded file is empty or missing for {video_id}")

        os.rename(temp_path, final_path)
        return final_path

    async def download_path(self, video_id: str, dtype: str = "audio") -> str:
        """
        Same-server optimisation: ask the API for the local filepath instead of
        streaming the file. Only works when your bot and the API share the same
        filesystem (e.g. both on the same VPS).
        """
        data = await self._get("/download/path", {"id": video_id, "type": dtype}, timeout=self.timeout)
        return data["filepath"]

    # --- Convenience ---

    async def search_and_download_audio(self, query: str) -> tuple[dict, str]:
        """
        One-shot: search + download audio.
        Returns (track_info, local_filepath).

        Example:
            info, path = await api.search_and_download_audio("Faded Alan Walker")
            await call.play(chat_id, tgtypes.MediaStream(path))
        """
        results = await self.search(query, limit=1)
        if not results:
            raise BlacAPIError(f"No results for: {query}")
        track = results[0]
        filepath = await self.download_audio(track["id"])
        return track, filepath

    async def search_and_download_video(self, query: str) -> tuple[dict, str]:
        """One-shot: search + download video. Returns (track_info, local_filepath)."""
        results = await self.search(query, limit=1)
        if not results:
            raise BlacAPIError(f"No results for: {query}")
        track = results[0]
        filepath = await self.download_video(track["id"])
        return track, filepath

    @staticmethod
    def _guess_ext(content_type: str, disposition: str, dtype: str) -> str:
        """Determine file extension from Content-Type or Content-Disposition headers."""
        if "filename=" in disposition:
            fname = disposition.split("filename=")[-1].strip().strip('"\'')
            ext = os.path.splitext(fname)[1]
            if ext:
                return ext
        if "mp4" in content_type and "audio" not in content_type:
            return ".mp4"
        if "m4a" in content_type or ("mp4" in content_type and "audio" in content_type):
            return ".m4a"
        if "mpeg" in content_type or "mp3" in content_type:
            return ".mp3"
        if "ogg" in content_type or "opus" in content_type:
            return ".opus"
        return ".mp4" if dtype == "video" else ".m4a"

# blacmusic.py — Blac Music API client SDK
#
# Drop this file into your bot project and import BlacAPI.
#
# Quick start:
#   from blacmusic import BlacAPI
#   api = BlacAPI(base_url="http://localhost:8000", api_key="YOUR_KEY")
#
#   results  = await api.search("Alan Walker Faded")
#   track    = results[0]
#   filepath = await api.download_audio(track["id"])   # for /play
#   filepath = await api.download_video(track["id"])   # for /vplay
#   info     = await api.get_info("VIDEO_ID")
#   stream   = await api.get_live_url("VIDEO_ID")
#   ids      = await api.get_playlist("https://youtube.com/playlist?list=PL...")
#
# Powered by Blac — https://t.me/blcqt | https://t.me/TechTipsCode

import asyncio
import os
from typing import Optional

import aiohttp

__version__ = "1.0.0"
__author__  = "Blac"
__dev__     = "https://t.me/blcqt"
__channel__ = "https://t.me/TechTipsCode"


class BlacAPIError(Exception):
    pass


class BlacAPI:
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
                    f"Cannot connect to API at {self.base_url}. Is the server running?"
                )
            except asyncio.TimeoutError:
                raise BlacAPIError(f"Request to {path} timed out after {timeout}s")

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        data = await self._get("/search/youtube", {"q": query, "limit": limit})
        return data["results"]

    async def get_playlist(self, playlist_url: str, limit: int = 50) -> list[str]:
        data = await self._get("/search/playlist", {"url": playlist_url, "limit": limit})
        return data["video_ids"]

    async def get_info(self, video_id: str) -> dict:
        data = await self._get("/info/youtube", {"id": video_id})
        return data["video"]

    async def get_live_url(self, video_id: str) -> str:
        data = await self._get("/info/live", {"id": video_id}, timeout=45)
        return data["stream_url"]

    async def download_audio(self, video_id: str) -> str:
        return await self._download(video_id, "audio")

    async def download_video(self, video_id: str) -> str:
        return await self._download(video_id, "video")

    async def _download(self, video_id: str, dtype: str) -> str:
        audio_exts = [".m4a", ".mp3", ".webm", ".opus", ".ogg", ".flac"]
        video_exts = [".mp4", ".mkv", ".webm"]
        for ext in (video_exts if dtype == "video" else audio_exts):
            p = os.path.join(self.download_dir, f"{video_id}{ext}")
            if os.path.isfile(p) and os.path.getsize(p) > 1024:
                return p

        temp_path = os.path.join(self.download_dir, f"{video_id}.tmp")
        final_path = None

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
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        raise BlacAPIError(f"Write error during download: {exc}")

            except aiohttp.ClientConnectorError:
                raise BlacAPIError(f"Cannot connect to API at {self.base_url}")
            except asyncio.TimeoutError:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise BlacAPIError(f"Download timed out after {self.timeout}s")

        if not os.path.isfile(temp_path) or os.path.getsize(temp_path) < 1024:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise BlacAPIError(f"Downloaded file is empty for {video_id}")

        os.rename(temp_path, final_path)
        return final_path

    async def download_path(self, video_id: str, dtype: str = "audio") -> str:
        data = await self._get("/download/path", {"id": video_id, "type": dtype}, timeout=self.timeout)
        return data["filepath"]

    async def search_and_download_audio(self, query: str) -> tuple[dict, str]:
        results = await self.search(query, limit=1)
        if not results:
            raise BlacAPIError(f"No results for: {query}")
        track    = results[0]
        filepath = await self.download_audio(track["id"])
        return track, filepath

    async def search_and_download_video(self, query: str) -> tuple[dict, str]:
        results = await self.search(query, limit=1)
        if not results:
            raise BlacAPIError(f"No results for: {query}")
        track    = results[0]
        filepath = await self.download_video(track["id"])
        return track, filepath

    @staticmethod
    def _guess_ext(content_type: str, disposition: str, dtype: str) -> str:
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

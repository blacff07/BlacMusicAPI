# errors.py — turning "something went wrong inside yt-dlp" into an accurate,
# machine-useful HTTP status instead of a blanket 404 that hides the cause.
#
# A bot calling this API should be able to tell the difference between
# "this video genuinely doesn't exist" (404 — stop retrying, tell the user)
# and "the server is missing ffmpeg" (500 — an operator problem) or
# "YouTube is throttling this IP" (429 — back off and retry later) without
# scraping log files to find out.


class ResolutionError(Exception):
    """Base class for a classified stream-resolution failure."""
    status_code = 502

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class VideoNotFoundError(ResolutionError):
    """The video is genuinely unavailable, private, or removed."""
    status_code = 404


class DependencyMissingError(ResolutionError):
    """A required system binary (Node.js, ffmpeg) is missing on the server."""
    status_code = 500


class UpstreamBlockedError(ResolutionError):
    """YouTube is rate-limiting or blocking this server's egress IP."""
    status_code = 429


class ResolutionTimeoutError(ResolutionError):
    """Extraction did not complete within the configured timeout."""
    status_code = 504


_DEPENDENCY_MARKERS = ("node", "node.js", "ffmpeg")
_BLOCKED_MARKERS = (
    "sign in to confirm", "not a bot", "429", "too many requests",
    "rate-limit", "rate limit",
)
_NOT_FOUND_MARKERS = (
    "video unavailable", "private video", "no longer available",
    "does not exist", "has been removed", "account associated",
    "this video is unavailable",
)


def classify(exc: Exception) -> ResolutionError:
    """Map a raw yt-dlp/asyncio exception to a classified ResolutionError."""
    import asyncio

    if isinstance(exc, ResolutionError):
        return exc
    if isinstance(exc, asyncio.TimeoutError):
        return ResolutionTimeoutError(
            "Stream resolution timed out. Check that Node.js and ffmpeg are "
            "installed on the server, and that this server's IP isn't being "
            "throttled by YouTube (common on cloud/datacenter IP ranges)."
        )

    msg = str(exc).lower()

    if any(m in msg for m in _DEPENDENCY_MARKERS) and (
        "not found" in msg or "no such file" in msg or "executable" in msg or "runtime" in msg
    ):
        return DependencyMissingError(f"A required system dependency is missing on the server: {exc}")

    if any(m in msg for m in _BLOCKED_MARKERS):
        return UpstreamBlockedError(f"YouTube is rate-limiting or blocking this server's IP: {exc}")

    if any(m in msg for m in _NOT_FOUND_MARKERS):
        return VideoNotFoundError(f"Video unavailable: {exc}")

    return ResolutionError(f"Stream resolution failed: {exc}", status_code=502)

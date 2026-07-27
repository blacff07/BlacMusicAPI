import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from blacapi.config import settings
from blacapi.errors import ResolutionError
from blacapi.logger import logger
from blacapi.proxy import close_client, get_client
from blacapi.routes import health, lyrics, youtube
from blacapi import stats


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_client()  # warm the shared connection pool before the first request
    logger.info(f"{settings.WATERMARK} online — workers={settings.WORKERS}, docs={settings.ENABLE_DOCS}")
    yield
    await close_client()
    logger.info(f"{settings.WATERMARK} shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.WATERMARK,
        description=(
            "Fast, cookieless, self-hostable YouTube streaming API for Telegram "
            "music/video bots.\n\n"
            f"By **Blac** — [@blcqt]({settings.DEV_URL}) | [Channel]({settings.CHANNEL_URL})"
        ),
        version="2.0.0",
        docs_url="/docs" if settings.ENABLE_DOCS else None,
        redoc_url="/redoc" if settings.ENABLE_DOCS else None,
        lifespan=lifespan,
        # Faster JSON serialization for metadata routes (search/info/audio
        # formats etc). Has zero effect on /play/* — those return explicit
        # StreamingResponse/Response objects, which always bypass this.
        default_response_class=ORJSONResponse,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    if settings.RATE_LIMIT_PER_MIN > 0:
        app.add_middleware(RateLimitMiddleware)

    app.add_middleware(StatsMiddleware)

    app.include_router(health.router)
    app.include_router(youtube.router, prefix="/api/youtube", tags=["YouTube"])
    app.include_router(lyrics.router, prefix="/api", tags=["Lyrics"])

    @app.exception_handler(ResolutionError)
    async def resolution_error_handler(request: Request, exc: ResolutionError):
        # Already logged with full context at the point it was raised
        # (resolver.py / proxy.py) — this just translates it to a response.
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "success": False, "error": str(exc)})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "success": False, "error": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors()]
        return JSONResponse(status_code=422, content={"ok": False, "success": False, "error": "; ".join(errors)})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"ok": False, "success": False, "error": "Internal server error"})

    return app


class StatsMiddleware:
    """Counts requests per path for the /api/stats endpoint. Route params
    aren't in the path template here (no Starlette routing context this
    early), so this counts the raw request path — fine for an at-a-glance
    view, just don't expect /api/youtube/info and /api/youtube/info?id=x
    to be distinguished (they aren't, they're the same path either way)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            stats.note_request(scope.get("path", "unknown"))
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    """Tiny in-memory per-IP token bucket. Off by default (RATE_LIMIT_PER_MIN=0)."""

    def __init__(self, app):
        self.app = app
        self._hits: dict[str, list[float]] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        ip = client[0] if client else "unknown"
        now = time.monotonic()
        window = self._hits.setdefault(ip, [])
        window[:] = [t for t in window if now - t < 60]

        if len(window) >= settings.RATE_LIMIT_PER_MIN:
            response = JSONResponse(status_code=429, content={"ok": False, "success": False, "error": "Rate limit exceeded"})
            await response(scope, receive, send)
            return

        window.append(now)
        if len(self._hits) > 5000:
            for k in list(self._hits.keys())[:1000]:
                self._hits.pop(k, None)

        await self.app(scope, receive, send)

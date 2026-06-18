from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from blacapi.core.cleaner import start_cleaner
from blacapi.core.config import settings
from blacapi.core.logger import logger
from blacapi.routes import download, health, info, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Blac Music API is online")
    await start_cleaner()
    yield
    logger.info("Blac Music API shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Blac Music API",
        description=(
            "Fast, free, self-hosted YouTube music API for Telegram bots.\n\n"
            f"By **Blac** — [@blcqt]({settings.DEV_URL}) | "
            f"[TechTipsCode]({settings.CHANNEL_URL})"
        ),
        version="1.0.0",
        docs_url="/docs" if settings.ENABLE_DOCS else None,
        redoc_url="/redoc" if settings.ENABLE_DOCS else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(search.router,   prefix="/search",   tags=["Search"])
    app.include_router(info.router,     prefix="/info",     tags=["Info"])
    app.include_router(download.router, prefix="/download", tags=["Download"])

    # Let HTTP errors (400, 401, 404, etc.) pass through as-is
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": exc.detail},
        )

    # Validation errors (bad query params, wrong types)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "; ".join(errors)},
        )

    # Truly unexpected errors only
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error on {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Internal server error"},
        )

    return app

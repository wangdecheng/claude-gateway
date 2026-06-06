"""DEPRECATED: Legacy standalone FastAPI app.

This module is kept for reference only. The production app is now created in
`api/app.py` and launched via `server.py`.

Do NOT import or use `app.main.app` — it is no longer the active application.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger("high-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create the deprecated legacy FastAPI app (reference only)."""
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Custom Exception ---
    from app.exceptions import AppException  # noqa: E402

    # --- Exception Handlers (uniform error format) ---
    def _extract_first_error(exc: RequestValidationError) -> str:
        """Extract the first user-facing error message from validation errors."""
        for error in exc.errors():
            msg = error.get("msg", "")
            if "Value error, " in msg:
                return msg.split("Value error, ", 1)[1]
            if error.get("type") == "missing":
                field = error.get("loc", [])[-1] if error.get("loc") else "field"
                return f"{field} 是必填项"
        return "请求参数校验失败"

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": _extract_first_error(exc), "code": "VALIDATION_ERROR"},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "code": "INTERNAL_ERROR"},
        )

    # --- Routers ---
    from app.routers import (
        admin_channels,
        admin_models,
        admin_providers,
        api_keys,
        auth,
        models,
        payment,
        proxy,
        redemption,
        usage,
        v1_models,
    )  # noqa: E402

    app.include_router(auth.router)
    app.include_router(api_keys.router)
    app.include_router(proxy.router)
    app.include_router(usage.router)
    app.include_router(models.router)
    app.include_router(v1_models.router)
    app.include_router(redemption.router)
    app.include_router(payment.router)
    app.include_router(admin_models.router)
    app.include_router(admin_providers.router)
    app.include_router(admin_channels.router)

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    app = create_app()

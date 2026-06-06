"""FastAPI application factory — merged protocol + commerce layers."""

import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from config.logging_config import configure_logging
from config.paths import server_log_path
from config.settings import get_settings
from core.trace import extract_claude_session_id_from_headers, trace_event
from providers.exceptions import ProviderError

from .routes import router as anthropic_router
from .validation_log import summarize_request_validation_body


def create_app() -> FastAPI:
    """Create and configure the merged FastAPI application."""
    settings = get_settings()
    configure_logging(server_log_path(), verbose_third_party=settings.log_raw_api_payloads)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        from sqlalchemy import select

        from app.database import Base

        engine, session_factory = _create_engine_and_sessionmaker(settings.database_url)
        app.state.db_engine = engine
        app.state.db_session_factory = session_factory

        # Create tables (dev convenience; production uses alembic)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed data if DB is empty
        from app.models.user import User

        async with session_factory() as session:
            result = await session.execute(select(User).limit(1))
            if result.scalar_one_or_none() is None:
                from app.seed import seed_dev_data

                await seed_dev_data(db=session)
                await session.commit()
                logger.info("Database seeded with default data")

        # Initialize provider registry
        from providers.registry import ProviderRegistry

        app.state.provider_registry = ProviderRegistry(settings=settings)

        logger.info("Application startup complete")
        yield

        # Shutdown
        reg = getattr(app.state, "provider_registry", None)
        if reg is not None:
            await reg.cleanup()
        await engine.dispose()
        logger.info("Shutdown complete")

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # HTTP correlation middleware
    @app.middleware("http")
    async def trace_http_correlation(request: Request, call_next):
        claude_sid = extract_claude_session_id_from_headers(request.headers)
        with logger.contextualize(
            http_method=request.method,
            http_path=request.url.path,
            claude_session_id=claude_sid,
        ):
            response = await call_next(request)
        return response

    # === Proxy routes (POST /v1/messages — billing-integrated) ===
    # Register proxy router FIRST so its /v1/messages takes precedence
    from app.routers import proxy

    app.include_router(proxy.router)

    # === Protocol routes (Anthropic Messages API — remaining routes) ===
    app.include_router(anthropic_router)

    # === Commerce routes (JWT auth, billing, admin) ===
    from app.routers import (
        admin_channels,
        admin_models,
        admin_providers,
        api_keys,
        auth,
        models,
        payment,
        redemption,
        usage,
        v1_models,
    )

    app.include_router(auth.router)
    app.include_router(api_keys.router)
    app.include_router(usage.router)
    app.include_router(models.router)
    app.include_router(v1_models.router)
    app.include_router(redemption.router)
    app.include_router(payment.router)
    app.include_router(admin_models.router)
    app.include_router(admin_providers.router)
    app.include_router(admin_channels.router)

    # === Health check ===
    @app.get("/api/health")
    async def health_check():
        return {"status": "ok"}

    # === Exception handlers ===
    from app.exceptions import AppException

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        body: Any
        try:
            body = await request.json()
        except Exception as e:
            body = {"_json_error": type(e).__name__}
        message_summary, tool_names = summarize_request_validation_body(body)
        trace_event(
            stage="ingress",
            event="server.request.validation_failed",
            source="api",
            path=request.url.path,
            error_locs=[list(error.get("loc", ())) for error in exc.errors()],
            error_types=[str(error.get("type", "")) for error in exc.errors()],
            message_summary=message_summary,
            tool_names=tool_names,
        )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        if settings.log_api_error_tracebacks:
            logger.error(
                "Provider Error: error_type={} status_code={} message={}",
                exc.error_type,
                exc.status_code,
                exc.message,
            )
        else:
            logger.error(
                "Provider Error: error_type={} status_code={}", exc.error_type, exc.status_code
            )
        return JSONResponse(status_code=exc.status_code, content=exc.to_anthropic_format())

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        if settings.log_api_error_tracebacks:
            logger.error("General Error: {}", exc)
            logger.error(traceback.format_exc())
        else:
            logger.error(
                "General Error: path={} method={} exc_type={}",
                request.url.path,
                request.method,
                type(exc).__name__,
            )
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {"type": "api_error", "message": "An unexpected error occurred."},
            },
        )

    return app


def _create_engine_and_sessionmaker(database_url: str):
    """Create engine and session factory from a database URL."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    if "sqlite" in database_url:
        engine = create_async_engine(
            database_url.replace("sqlite:///", "sqlite+aiosqlite:///"),
            echo=False,
        )
    else:
        engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory

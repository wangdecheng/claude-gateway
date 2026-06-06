"""Dependency injection for FastAPI — DB-backed API key auth."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from config.settings import get_settings as _get_settings
from providers.registry import ProviderRegistry

logger = logging.getLogger("cloude-gateway.auth")
API_KEY_TOUCH_TIMEOUT_SECONDS = 1.0


def get_settings() -> Settings:
    return _get_settings()


async def get_db(request: Request) -> AsyncSession:
    """Get DB session from app state (set during lifespan startup)."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


async def _touch_api_key_last_used_once(session_factory, api_key_id: int) -> None:
    from app.models.api_key import ApiKey

    async with session_factory() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key_id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await session.commit()


async def _touch_api_key_last_used(session_factory, api_key_id: int) -> None:
    try:
        await asyncio.wait_for(
            _touch_api_key_last_used_once(session_factory, api_key_id),
            timeout=API_KEY_TOUCH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Skipped API key last_used_at update after lock timeout")
    except Exception:
        logger.exception("Failed to update API key last_used_at")


async def require_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple:
    """Validate API key from x-api-key or Authorization header against DB.

    Returns (User, ApiKey) tuple for downstream billing.
    """
    import bcrypt

    from app.models.api_key import ApiKey
    from app.models.user import User

    header = (
        request.headers.get("x-api-key")
        or request.headers.get("authorization")
        or request.headers.get("anthropic-auth-token")
    )
    if not header:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Extract token: support both "x-api-key: sk-..." and "Authorization: Bearer sk-..."
    token = header
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1]

    token = token.strip()
    if ":" in token:
        token = token.split(":", 1)[0]
    if not token.startswith("sk-"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    # Look up by prefix (first 10 chars)
    prefix = token[:10]
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.status == "active")
    )
    api_keys = result.scalars().all()

    for ak in api_keys:
        if bcrypt.checkpw(token.encode("utf-8"), ak.key_hash.encode("utf-8")):
            # Get associated user
            user_result = await db.execute(
                select(User).where(User.id == ak.user_id, User.status == "active")
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=401, detail="User not found or inactive")

            session_factory = getattr(request.app.state, "db_session_factory", None)
            if session_factory is not None:
                asyncio.create_task(_touch_api_key_last_used(session_factory, ak.id))

            return user, ak

    raise HTTPException(status_code=401, detail="Invalid API key")


def get_provider_registry(request: Request) -> ProviderRegistry:
    """Get the app-scoped provider registry."""
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:
        from providers.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError("Provider registry not configured")
    return reg

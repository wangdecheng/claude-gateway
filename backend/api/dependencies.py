"""Dependency injection for FastAPI — DB-backed API key auth."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from config.settings import get_settings as _get_settings
from providers.registry import ProviderRegistry


def get_settings() -> Settings:
    return _get_settings()


async def get_db(request: Request) -> AsyncSession:
    """Get DB session from app state (set during lifespan startup)."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


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

    header = request.headers.get("x-api-key") or request.headers.get("authorization")
    if not header:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Extract token: support both "x-api-key: sk-..." and "Authorization: Bearer sk-..."
    token = header
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1]

    token = token.strip()
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

            # Update last_used_at
            from datetime import datetime

            ak.last_used_at = datetime.utcnow()
            await db.flush()

            return user, ak

    raise HTTPException(status_code=401, detail="Invalid API key")


def get_provider_registry(request: Request) -> ProviderRegistry:
    """Get the app-scoped provider registry."""
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:
        from providers.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError("Provider registry not configured")
    return reg

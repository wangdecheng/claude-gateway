import secrets

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppException
from app.models.api_key import ApiKey
from app.models.provider import Provider
from app.models.user import User


def generate_key() -> tuple[str, str]:
    """Generate a new API key and its prefix.

    Returns (raw_key, key_prefix)
    raw_key:  "sk-a1b2c3d4e5f6..."
    key_prefix: "sk-a1b2c3" (first 10 chars for display)
    """
    raw_key = "sk-" + secrets.token_hex(20)  # 40 hex + "sk-" = 43 chars
    key_prefix = raw_key[:10]  # "sk-a1b2c3d"
    return raw_key, key_prefix


def hash_key(raw_key: str) -> str:
    return bcrypt.hashpw(raw_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def create_api_key(
    db: AsyncSession, user: User, name: str, channel_id: int
) -> tuple[ApiKey, str]:
    raw_key, key_prefix = generate_key()

    api_key = ApiKey(
        user_id=user.id,
        name=name,
        key_prefix=key_prefix,
        key_hash=hash_key(raw_key),
        status="active",
        channel_id=channel_id,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, raw_key


async def list_api_keys(db: AsyncSession, user: User) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id, ApiKey.status == "active")
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(db: AsyncSession, user: User, key_id: int) -> None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise AppException(status_code=404, error="密钥不存在", code="KEY_NOT_FOUND")
    if api_key.status == "revoked":
        raise AppException(status_code=400, error="密钥已撤销", code="KEY_ALREADY_REVOKED")

    api_key.status = "revoked"
    await db.commit()


async def update_api_key(
    db: AsyncSession,
    user: User,
    key_id: int,
    *,
    channel_id: int | None,
) -> ApiKey:
    """Update an existing active key's bound channel.

    channel_id=None clears the binding (back to 'auto, by model default').
    A positive channel_id switches the binding; the provider must be active.
    """
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise AppException(status_code=404, error="密钥不存在", code="KEY_NOT_FOUND")
    if api_key.status != "active":
        raise AppException(status_code=400, error="密钥已撤销", code="KEY_ALREADY_REVOKED")

    if channel_id is not None:
        p = await db.execute(select(Provider).where(Provider.id == channel_id))
        provider = p.scalar_one_or_none()
        if not provider or provider.status != "active":
            raise AppException(
                status_code=400, error="选择的渠道不可用", code="CHANNEL_UNAVAILABLE"
            )
        api_key.channel_id = channel_id
    else:
        api_key.channel_id = None

    await db.commit()
    await db.refresh(api_key)
    return api_key

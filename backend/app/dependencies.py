from datetime import datetime, timezone

import bcrypt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.exceptions import AppException
from app.models.api_key import ApiKey
from app.models.user import User
from app.services.auth_service import decode_jwt


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract JWT from cookie, validate, and return the current user."""
    token = request.cookies.get("high_api_session")
    if not token:
        raise AppException(status_code=401, error="请先登录", code="UNAUTHORIZED")

    payload = decode_jwt(token)
    user_id = payload.get("user_id")
    if not user_id:
        raise AppException(status_code=401, error="无效的登录凭证", code="INVALID_TOKEN")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(status_code=401, error="用户不存在", code="USER_NOT_FOUND")
    if user.status != "active":
        raise AppException(status_code=403, error="账号已被禁用", code="USER_DISABLED")

    return user


async def get_current_user_from_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple[User, ApiKey]:
    """Authenticate via API key in Authorization: Bearer <sk-...> header.

    Returns (user, api_key) on success.
    Updates api_key.last_used_at.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise AppException(
            status_code=401,
            error="缺少认证信息，请在 Authorization 头中提供 Bearer <sk-...>",
            code="MISSING_API_KEY",
        )

    raw_key = auth_header[7:].strip()  # Remove "Bearer " prefix
    if not raw_key.startswith("sk-") or len(raw_key) < 20:
        raise AppException(
            status_code=401,
            error="无效的 API 密钥格式",
            code="INVALID_API_KEY_FORMAT",
        )

    # Look up by prefix first for efficiency
    key_prefix = raw_key[:10]
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_prefix == key_prefix,
            ApiKey.status == "active",
        )
    )
    candidates = result.scalars().all()

    # Verify bcrypt hash against each candidate
    matched_key = None
    for candidate in candidates:
        if bcrypt.checkpw(raw_key.encode("utf-8"), candidate.key_hash.encode("utf-8")):
            matched_key = candidate
            break

    if not matched_key:
        raise AppException(
            status_code=401,
            error="无效的 API 密钥",
            code="INVALID_API_KEY",
        )

    # Fetch the associated user
    user_result = await db.execute(select(User).where(User.id == matched_key.user_id))
    user = user_result.scalar_one_or_none()
    if not user or user.status != "active":
        raise AppException(
            status_code=401,
            error="用户不存在或已被禁用",
            code="USER_NOT_FOUND",
        )

    # Update last_used_at via ORM attribute so the in-memory object stays consistent
    matched_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return user, matched_key


async def get_current_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract JWT, validate, and require admin role."""
    user = await get_current_user(request, db)
    if user.role != "admin":
        raise AppException(status_code=403, error="权限不足，需要管理员权限", code="FORBIDDEN")
    return user

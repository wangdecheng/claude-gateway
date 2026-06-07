from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import AppException
from app.models.user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_jwt(user_id: int, role: str) -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_expire_seconds),
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_public_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise AppException(status_code=401, error="登录已过期", code="TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise AppException(status_code=401, error="无效的登录凭证", code="INVALID_TOKEN")


async def register(db: AsyncSession, email: str, password: str) -> User:
    # Check for duplicate email
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        raise AppException(status_code=409, error="该邮箱已注册", code="EMAIL_EXISTS")

    # Create user
    user = User(
        email=email,
        password_hash=hash_password(password),
        balance=0,
        role="user",
        status="active",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login(db: AsyncSession, email: str, password: str) -> User:
    # Find user by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Use uniform error to prevent email enumeration
    if not user:
        raise AppException(status_code=401, error="邮箱或密码错误", code="INVALID_CREDENTIALS")

    # Verify password
    if not verify_password(password, user.password_hash):
        raise AppException(status_code=401, error="邮箱或密码错误", code="INVALID_CREDENTIALS")

    # Check account status
    if user.status != "active":
        raise AppException(
            status_code=403, error="账号已被禁用，请联系管理员", code="USER_DISABLED"
        )

    return user


# --- Reset Token ---


def generate_reset_token(user_id: int) -> str:
    """Generate a short-lived JWT for password reset (15 min)."""
    payload = {
        "user_id": user_id,
        "purpose": "password_reset",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm)


def decode_reset_token(token: str) -> dict:
    """Decode and validate a password reset token."""
    try:
        payload = jwt.decode(token, settings.jwt_public_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise AppException(
            status_code=400, error="重置链接已过期，请重新申请", code="RESET_TOKEN_EXPIRED"
        )
    except jwt.InvalidTokenError:
        raise AppException(status_code=400, error="无效的重置令牌", code="INVALID_RESET_TOKEN")

    if payload.get("purpose") != "password_reset":
        raise AppException(status_code=400, error="无效的重置令牌", code="INVALID_RESET_TOKEN")

    return payload


# --- Password Management ---


async def change_password(
    db: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    """Change password for an authenticated user."""
    if not verify_password(current_password, user.password_hash):
        raise AppException(status_code=400, error="当前密码不正确", code="WRONG_PASSWORD")

    user.password_hash = hash_password(new_password)
    await db.commit()


async def forgot_password(db: AsyncSession, email: str) -> str | None:
    """Generate a reset token if the email exists. Returns None if not found
    (to prevent email enumeration — caller should still return 200)."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return None
    return generate_reset_token(user.id)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """Reset password using a valid reset token."""
    payload = decode_reset_token(token)
    user_id = payload.get("user_id")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(status_code=400, error="用户不存在", code="USER_NOT_FOUND")

    user.password_hash = hash_password(new_password)
    await db.commit()

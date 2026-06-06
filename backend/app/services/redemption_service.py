"""Redemption service — code validation, redemption, and history."""

import logging
import re
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppException
from app.models.redemption_code import RedemptionCode, RedemptionUsage
from app.models.user import User

logger = logging.getLogger("high-api")

# REDM-XXXX-XXXX-XXXX: prefix + 3 groups of 4 alphanumeric chars
_CODE_PATTERN = re.compile(r"^REDM-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


def _is_valid_code_format(raw_code: str) -> bool:
    return bool(_CODE_PATTERN.match(raw_code))


async def redeem(db: AsyncSession, user_id: int, raw_code: str) -> tuple[int, int]:
    """Validate and redeem a code, crediting the user's balance.

    Returns (amount_credited, new_balance), both in 分.

    All operations run in a single transaction. Raises AppException on failure.
    """
    raw_code = raw_code.strip().upper()

    # 1. Format check (cheap, runs before any DB access)
    if not _is_valid_code_format(raw_code):
        raise AppException(
            status_code=400,
            error="兑换码格式无效",
            code="INVALID_CODE_FORMAT",
        )

    # 2. Verify user exists and lock the row (fail-fast, prevents lost-update)
    user_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = user_result.scalar_one_or_none()
    if not user:
        raise AppException(
            status_code=404,
            error="用户不存在",
            code="USER_NOT_FOUND",
        )

    # 3. Find by prefix — lock matching rows to prevent concurrent redemption
    code_prefix = raw_code[:9]  # "REDM-A3F2"
    result = await db.execute(
        select(RedemptionCode)
        .where(RedemptionCode.code_prefix == code_prefix)
        .order_by(RedemptionCode.id)
        .with_for_update()
    )
    candidates = result.scalars().all()

    # 4. bcrypt verify
    matched_code: RedemptionCode | None = None
    for c in candidates:
        if bcrypt.checkpw(raw_code.encode("utf-8"), c.code_hash.encode("utf-8")):
            matched_code = c
            break

    if not matched_code:
        raise AppException(
            status_code=400,
            error="兑换码无效",
            code="CODE_NOT_FOUND",
        )

    # 5. Amount validation (defense in depth — DB constraint also covers this)
    if matched_code.amount <= 0:
        raise AppException(
            status_code=400,
            error="兑换码金额无效",
            code="INVALID_CODE_AMOUNT",
        )

    # 6. Status checks
    if matched_code.status == "used":
        raise AppException(
            status_code=400,
            error="该兑换码已被使用",
            code="CODE_ALREADY_USED",
        )

    now = datetime.now(timezone.utc)
    # SQLite stores naive datetimes; PostgreSQL stores timezone-aware.
    # Normalize both to UTC-aware for comparison.
    expires = matched_code.expires_at
    if expires is None:
        raise AppException(
            status_code=400,
            error="兑换码数据异常",
            code="CODE_DATA_ERROR",
        )
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        # Mark expired in-memory; the exception below rolls back the txn.
        # Expiry detection is idempotent — rechecked on every attempt.
        matched_code.status = "expired"
        raise AppException(
            status_code=400,
            error="该兑换码已过期",
            code="CODE_EXPIRED",
        )

    if matched_code.status != "issued":
        raise AppException(
            status_code=400,
            error="该兑换码不可用",
            code="CODE_NOT_AVAILABLE",
        )

    # 7. Transaction: mark used → record usage → credit balance
    matched_code.status = "used"

    usage = RedemptionUsage(
        user_id=user_id,
        code_id=matched_code.id,
        amount=matched_code.amount,
    )
    db.add(usage)

    user.balance += matched_code.amount

    await db.commit()

    return matched_code.amount, user.balance


async def get_redemption_history(db: AsyncSession, user_id: int, limit: int = 20) -> list[dict]:
    """Return the user's redemption history, newest first."""
    result = await db.execute(
        select(
            RedemptionUsage.id,
            RedemptionCode.code_prefix,
            RedemptionUsage.amount,
            RedemptionUsage.created_at,
        )
        .join(RedemptionCode, RedemptionCode.id == RedemptionUsage.code_id)
        .where(RedemptionUsage.user_id == user_id)
        .order_by(RedemptionUsage.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "id": row.id,
            "code_masked": _mask_code(row.code_prefix),
            "amount": row.amount,
            "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.created_at else "",
        }
        for row in rows
    ]


def _mask_code(code_prefix: str) -> str:
    """REDM-A3F2 → REDM-****-A3F2"""
    if len(code_prefix) < 9:
        return code_prefix
    return f"{code_prefix[:5]}****-{code_prefix[-4:]}"


def hash_code(raw_code: str) -> str:
    """Hash a redemption code with bcrypt."""
    return bcrypt.hashpw(raw_code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

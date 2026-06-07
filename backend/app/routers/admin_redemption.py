"""Admin redemption-code management router."""

import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.redemption_code import RedemptionCode
from app.models.user import User
from app.schemas.redemption import (
    AdminRedemptionCreateRequest,
    AdminRedemptionCreateResponse,
)
from app.services.redemption_service import hash_code

router = APIRouter(prefix="/api/admin/redemption", tags=["admin-redemption"])

_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "REDM-" + "-".join(groups)


async def _create_unique_code(db: AsyncSession) -> str:
    for _ in range(5):
        raw_code = _generate_code()
        existing = await db.execute(
            select(RedemptionCode.id).where(RedemptionCode.code_prefix == raw_code[:9])
        )
        if existing.scalar_one_or_none() is None:
            return raw_code

    raise AppException(
        status_code=500,
        error="兑换码生成失败，请重试",
        code="REDEMPTION_CODE_GENERATION_FAILED",
    )


@router.post("", response_model=AdminRedemptionCreateResponse)
async def create_redemption_code(
    body: AdminRedemptionCreateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a one-time redemption code and return the full code once."""
    raw_code = await _create_unique_code(db)
    now = datetime.now(timezone.utc)
    item = RedemptionCode(
        code_hash=hash_code(raw_code),
        code_prefix=raw_code[:9],
        amount=body.amount,
        status="issued",
        expires_at=now + timedelta(days=body.expires_in_days),
        created_by=admin.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return AdminRedemptionCreateResponse(
        id=item.id,
        code=raw_code,
        codePrefix=item.code_prefix,
        amount=item.amount,
        status=item.status,
        expiresAt=item.expires_at.isoformat(),
        createdAt=item.created_at.isoformat(),
    )

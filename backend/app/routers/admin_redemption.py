"""Admin redemption-code management router."""

import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.redemption_code import RedemptionCode, RedemptionUsage
from app.models.user import User
from app.schemas.redemption import (
    AdminRedemptionCreateRequest,
    AdminRedemptionCreateResponse,
    AdminRedemptionListItem,
)
from app.services.redemption_service import hash_code

router = APIRouter(prefix="/api/admin/redemption", tags=["admin-redemption"])

_ALPHABET = string.ascii_uppercase + string.digits
_VALID_STATUSES = {"issued", "used", "expired"}


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


def _iso(value: datetime | None) -> str | None:
    """Render a datetime as ISO 8601, coercing naive (SQLite) to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _effective_status(row_status: str, expires_at: datetime | None, now: datetime) -> str:
    """If still 'issued' but past its expiry, report 'expired' (read-only)."""
    if row_status != "issued" or expires_at is None:
        return row_status
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return "expired" if exp < now else row_status


@router.get("", response_model=list[AdminRedemptionListItem])
async def list_redemption_codes(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(200, gt=0, le=500),
    status: str | None = Query(None, description="filter by effective status"),
):
    """List historical redemption codes, newest first.

    `status` filter is applied on the *effective* status (so an `issued`
    row whose `expires_at` has passed is matched by `status=expired`).
    """
    if status is not None and status not in _VALID_STATUSES:
        raise AppException(
            status_code=400,
            error=f"status 必须为 {sorted(_VALID_STATUSES)} 之一",
            code="INVALID_STATUS_FILTER",
        )

    creator = aliased(User)
    redeemer = aliased(User)

    stmt = (
        select(
            RedemptionCode.id,
            RedemptionCode.code_prefix,
            RedemptionCode.amount,
            RedemptionCode.status,
            RedemptionCode.expires_at,
            RedemptionCode.created_at,
            creator.email.label("created_by_email"),
            redeemer.email.label("used_by_email"),
            RedemptionUsage.created_at.label("used_at"),
        )
        .select_from(RedemptionCode)
        .join(creator, creator.id == RedemptionCode.created_by, isouter=True)
        .join(RedemptionUsage, RedemptionUsage.code_id == RedemptionCode.id, isouter=True)
        .join(redeemer, redeemer.id == RedemptionUsage.user_id, isouter=True)
        .order_by(RedemptionCode.created_at.desc(), RedemptionCode.id.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    now = datetime.now(timezone.utc)
    items: list[AdminRedemptionListItem] = []
    for r in rows:
        eff = _effective_status(r.status, r.expires_at, now)
        if status is not None and eff != status:
            continue
        items.append(
            AdminRedemptionListItem(
                id=r.id,
                codePrefix=r.code_prefix,
                amount=r.amount,
                status=eff,
                expiresAt=_iso(r.expires_at) or "",
                createdAt=_iso(r.created_at) or "",
                createdByEmail=r.created_by_email,
                usedByEmail=r.used_by_email,
                usedAt=_iso(r.used_at),
            )
        )
    return items

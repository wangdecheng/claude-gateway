"""Admin /api/admin/token-coefficients router — manage the global default and
per-model overrides for the token coefficient (discount) feature.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.model import Model
from app.models.token_coefficient import TokenCoefficientConfig
from app.models.user import User
from app.schemas.token_coefficient import (
    TokenCoefficientGlobalOut,
    TokenCoefficientGlobalUpdate,
    TokenCoefficientModelOut,
    TokenCoefficientModelUpsert,
    TokenCoefficientsOverview,
)
from app.services.token_coefficient_service import (
    GLOBAL_SCOPE,
    MODEL_SCOPE,
)

logger = logging.getLogger("cloude-gateway.admin_token_coefficients")

router = APIRouter(prefix="/api/admin/token-coefficients", tags=["admin-token-coefficients"])


async def _username_for(db: AsyncSession, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    from app.models.user import User as UserModel
    user = await db.get(UserModel, user_id)
    return user.email if user else None


@router.get("", response_model=TokenCoefficientsOverview)
async def get_overview(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the global coefficient and all per-model overrides."""
    result = await db.execute(select(TokenCoefficientConfig))
    rows = result.scalars().all()

    global_row = next((r for r in rows if r.scope_type == GLOBAL_SCOPE), None)
    override_rows = [r for r in rows if r.scope_type == MODEL_SCOPE and r.model_id is not None]

    global_meta = TokenCoefficientGlobalOut(
        coefficient=global_row.coefficient if global_row else 1.0,
        updatedAt=global_row.updated_at if global_row else datetime.now(timezone.utc),
        updatedByUsername=await _username_for(db, global_row.updated_by) if global_row else None,
    )

    overrides: list[TokenCoefficientModelOut] = []
    for r in override_rows:
        model = await db.get(Model, r.model_id)
        # Note: Model ORM has only `public_name`, not `name` — the schema's
        # `modelName` field is populated with `public_name` for consistency with
        # the rest of the admin UI (admin_channel.py uses the same pattern).
        overrides.append(TokenCoefficientModelOut(
            modelId=r.model_id,
            modelName=model.public_name if model else f"#{r.model_id}",
            modelPublicName=model.public_name if model else "",
            coefficient=r.coefficient,
            updatedAt=r.updated_at,
            updatedByUsername=await _username_for(db, r.updated_by),
        ))

    return TokenCoefficientsOverview(
        globalCoefficient=global_meta.coefficient,
        globalMeta=global_meta,
        overrides=overrides,
    )


@router.put("/global", response_model=TokenCoefficientGlobalOut)
async def update_global(
    data: TokenCoefficientGlobalUpdate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set the global default coefficient."""
    result = await db.execute(
        select(TokenCoefficientConfig).where(TokenCoefficientConfig.scope_type == GLOBAL_SCOPE)
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = TokenCoefficientConfig(
            scope_type=GLOBAL_SCOPE, model_id=None,
            coefficient=data.coefficient, updated_by=admin.id, updated_at=now,
        )
        db.add(row)
    else:
        row.coefficient = data.coefficient
        row.updated_by = admin.id
        row.updated_at = now
    await db.commit()
    await request.app.state.token_coefficient_service.invalidate()
    return TokenCoefficientGlobalOut(
        coefficient=row.coefficient,
        updatedAt=row.updated_at,
        updatedByUsername=admin.email,
    )


@router.put("/models/{model_id}", response_model=TokenCoefficientModelOut)
async def upsert_model(
    model_id: int,
    data: TokenCoefficientModelUpsert,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a per-model override."""
    model = await db.get(Model, model_id)
    if model is None:
        raise AppException(
            status_code=404, error=f"模型 #{model_id} 不存在", code="MODEL_NOT_FOUND"
        )

    result = await db.execute(
        select(TokenCoefficientConfig).where(
            TokenCoefficientConfig.scope_type == MODEL_SCOPE,
            TokenCoefficientConfig.model_id == model_id,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = TokenCoefficientConfig(
            scope_type=MODEL_SCOPE, model_id=model_id,
            coefficient=data.coefficient, updated_by=admin.id, updated_at=now,
        )
        db.add(row)
    else:
        row.coefficient = data.coefficient
        row.updated_by = admin.id
        row.updated_at = now
    await db.commit()
    await request.app.state.token_coefficient_service.invalidate()
    return TokenCoefficientModelOut(
        modelId=model_id,
        modelName=model.public_name,
        modelPublicName=model.public_name,
        coefficient=row.coefficient,
        updatedAt=row.updated_at,
        updatedByUsername=admin.email,
    )


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a per-model override (fall back to global)."""
    result = await db.execute(
        select(TokenCoefficientConfig).where(
            TokenCoefficientConfig.scope_type == MODEL_SCOPE,
            TokenCoefficientConfig.model_id == model_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        # idempotent: 204 even if no override existed
        return None
    await db.delete(row)
    await db.commit()
    await request.app.state.token_coefficient_service.invalidate()
    return None

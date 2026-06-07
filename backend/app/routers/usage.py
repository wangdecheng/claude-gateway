from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.usage import (
    UsageHistoryResponse,
    UsageStatsResponse,
)
from app.services.usage_service import get_user_usage_history, get_user_usage_stats

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get(
    "/stats",
    response_model=UsageStatsResponse,
)
async def usage_stats(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated usage statistics for the current user.

    Includes today's counts and daily breakdown for the specified period.
    """
    stats = await get_user_usage_stats(db, user=user, days=days)
    return {
        "todayCalls": stats["today_calls"],
        "todayTokens": stats["today_tokens"],
        "todayCostCents": stats["today_cost_cents"],
        "activeKeys": stats["active_keys"],
        "balanceCents": user.balance,
        "daily": [
            {
                "date": d["date"],
                "calls": d["calls"],
                "tokens": d["tokens"],
                "costCents": d["cost_cents"],
            }
            for d in stats["daily"]
        ],
    }


@router.get(
    "/history",
    response_model=UsageHistoryResponse,
)
async def usage_history(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize", description="每页数量"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated usage history for the current user."""
    records, total = await get_user_usage_history(
        db,
        user=user,
        page=page,
        page_size=page_size,
    )
    return {
        "records": [
            {
                "id": r.id,
                "model": r.model,
                "inputTokens": r.input_tokens,
                "cacheReadTokens": r.cache_read_tokens,
                "cacheCreationTokens": r.cache_creation_tokens,
                "outputTokens": r.output_tokens,
                "costCents": r.cost_cents,
                "createdAt": r.created_at,
            }
            for r in records
        ],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }

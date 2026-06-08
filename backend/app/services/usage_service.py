from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.model_provider_route import ModelProviderRoute
from app.models.provider import Provider
from app.models.usage import UsageRecord
from app.models.user import User


async def record_usage(
    db: AsyncSession,
    user_id: int,
    api_key_id: int,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_cents: int = 0,
) -> UsageRecord:
    """Record an API call usage entry.

    Flushes to the session but does NOT commit — the caller owns the
    transaction boundary so that usage + RequestLog (Epic 3) are atomic.
    """
    record = UsageRecord(
        user_id=user_id,
        api_key_id=api_key_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cost_cents=cost_cents,
    )
    db.add(record)
    await db.flush()
    return record


async def get_user_usage_stats(
    db: AsyncSession,
    user: User,
    days: int = 30,
) -> dict:
    """Get aggregated usage stats for the current user.

    Returns today's stats and daily breakdown for the given period.
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's stats
    today_result = await db.execute(
        select(
            func.count(UsageRecord.id).label("calls"),
            func.coalesce(
                func.sum(
                    UsageRecord.input_tokens
                    + UsageRecord.cache_read_tokens
                    + UsageRecord.cache_creation_tokens
                    + UsageRecord.output_tokens
                ), 0
            ).label("tokens"),
            func.coalesce(func.sum(UsageRecord.cost_cents), 0).label("cost"),
        ).where(
            UsageRecord.user_id == user.id,
            UsageRecord.created_at >= today_start,
        )
    )
    today = today_result.one()

    # Daily breakdown
    period_start = today_start - timedelta(days=days - 1)
    daily_result = await db.execute(
        select(
            func.date(UsageRecord.created_at).label("date"),
            func.count(UsageRecord.id).label("calls"),
            func.coalesce(
                func.sum(
                    UsageRecord.input_tokens
                    + UsageRecord.cache_read_tokens
                    + UsageRecord.cache_creation_tokens
                    + UsageRecord.output_tokens
                ), 0
            ).label("tokens"),
            func.coalesce(func.sum(UsageRecord.cost_cents), 0).label("cost"),
        )
        .where(
            UsageRecord.user_id == user.id,
            UsageRecord.created_at >= period_start,
        )
        .group_by(func.date(UsageRecord.created_at))
        .order_by(func.date(UsageRecord.created_at).desc())
    )
    daily = [
        {
            "date": str(row.date),
            "calls": row.calls,
            "tokens": row.tokens,
            "cost_cents": row.cost,
        }
        for row in daily_result.all()
    ]

    # Active key count
    key_result = await db.execute(
        select(func.count(ApiKey.id)).where(
            ApiKey.user_id == user.id,
            ApiKey.status == "active",
        )
    )
    active_keys = key_result.scalar_one()

    return {
        "today_calls": today.calls,
        "today_tokens": today.tokens,
        "today_cost_cents": today.cost,
        "active_keys": active_keys,
        "daily": daily,
    }


async def get_user_usage_history(
    db: AsyncSession,
    user: User,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[UsageRecord], int, dict[int, str]]:
    """Get paginated usage history for the current user.

    Returns (records, total, channel_map) where channel_map maps
    route_id -> channel name (looked up via ModelProviderRoute → Provider.channel_name).
    """
    # Total count
    count_result = await db.execute(
        select(func.count(UsageRecord.id)).where(UsageRecord.user_id == user.id)
    )
    total = count_result.scalar_one()

    # Records
    offset = (page - 1) * page_size
    result = await db.execute(
        select(UsageRecord)
        .where(UsageRecord.user_id == user.id)
        .order_by(UsageRecord.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    records = list(result.scalars().all())

    # Batch-fetch channel names referenced by these records
    # route_id -> ModelProviderRoute -> Provider.channel_name
    route_ids = {r.route_id for r in records if r.route_id is not None}
    channel_map: dict[int, str] = {}
    if route_ids:
        ch_result = await db.execute(
            select(ModelProviderRoute.id, Provider.channel_name)
            .join(Provider, Provider.id == ModelProviderRoute.provider_id)
            .where(ModelProviderRoute.id.in_(route_ids))
        )
        channel_map = {row[0]: row[1] or "" for row in ch_result.all()}

    return records, total, channel_map

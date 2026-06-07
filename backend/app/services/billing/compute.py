"""Cost computation for the async billing pipeline.

Prices are in micro-yuan per 1K tokens. Result is in cents (向上取整).
"""

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def compute_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    input_price_micro_yuan: int,
    output_price_micro_yuan: int,
    cache_read_price_micro_yuan: int,
    cache_creation_price_micro_yuan: int,
    channel_multiplier: float = 1.0,
) -> int:
    """Compute the cost in cents for a single request, rounding up.

    The caller is responsible for setting ``cache_creation_price_micro_yuan``
    to whatever they want to charge (industry default: input_price).
    """
    base = (
        input_tokens / 1000.0 * input_price_micro_yuan
        + output_tokens / 1000.0 * output_price_micro_yuan
        + cache_read_tokens / 1000.0 * cache_read_price_micro_yuan
        + cache_creation_tokens / 1000.0 * cache_creation_price_micro_yuan
    )
    return max(0, math.ceil(base * channel_multiplier / 10_000))


async def compute_costs_for_pending(
    pending: "PendingBilling",  # noqa: F821 — forward ref
    db: AsyncSession,
) -> int:
    """Load channel multiplier and model prices, then call compute_cost.

    cache_creation_price is set to input_price (industry default).
    """
    from app.models.model import ChannelConfig, Model
    from app.models.pending_billing import PendingBilling

    channel = await db.scalar(
        select(ChannelConfig).where(ChannelConfig.id == pending.channel_id)
    )
    model = await db.scalar(select(Model).where(Model.id == pending.model_id))
    return compute_cost(
        input_tokens=pending.input_tokens,
        output_tokens=pending.output_tokens,
        cache_read_tokens=pending.cache_read_tokens,
        cache_creation_tokens=pending.cache_creation_tokens,
        input_price_micro_yuan=model.input_price,
        output_price_micro_yuan=model.output_price,
        cache_read_price_micro_yuan=model.cache_read_price,
        cache_creation_price_micro_yuan=model.input_price,
        channel_multiplier=channel.multiplier,
    )

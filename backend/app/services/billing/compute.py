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
    channel_multiplier: float = 1.0,
) -> int:
    """Compute the cost in cents for a single request, rounding up.

    Pricing (cache_creation at input rate, cache_read at 1/10 input rate):
      cost = ((input_tokens + cache_creation_tokens + cache_read_tokens / 10)
                × input_price
              + output_tokens × output_price) × channel_multiplier
    """
    effective_input = input_tokens + cache_creation_tokens + cache_read_tokens / 10.0
    base_micro_yuan = (
        (effective_input / 1000.0) * input_price_micro_yuan
        + (output_tokens / 1000.0) * output_price_micro_yuan
    )
    return max(0, math.ceil(base_micro_yuan * channel_multiplier / 10_000))


async def compute_costs_for_pending(
    pending: "PendingBilling",  # noqa: F821 — forward ref
    db: AsyncSession,
) -> int:
    """Load provider multiplier and model prices, then call compute_cost."""
    from app.models.model import Model
    from app.models.model_provider_route import ModelProviderRoute
    from app.models.provider import Provider

    route = await db.scalar(
        select(ModelProviderRoute).where(ModelProviderRoute.id == pending.route_id)
    )
    if route is None:
        raise RuntimeError(f"ModelProviderRoute {pending.route_id} not found for billing")
    provider = await db.scalar(select(Provider).where(Provider.id == route.provider_id))
    model = await db.scalar(select(Model).where(Model.id == pending.model_id))
    return compute_cost(
        input_tokens=pending.input_tokens,
        output_tokens=pending.output_tokens,
        cache_read_tokens=pending.cache_read_tokens,
        cache_creation_tokens=pending.cache_creation_tokens,
        input_price_micro_yuan=model.input_price,
        output_price_micro_yuan=model.output_price,
        channel_multiplier=provider.multiplier,
    )

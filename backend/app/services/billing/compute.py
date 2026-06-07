"""Cost computation for the async billing pipeline.

Prices are in micro-yuan per 1K tokens. Result is in cents (向上取整).
"""

import math


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

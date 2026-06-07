"""Unit tests for billing compute_cost."""

import os
import sys

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)


def test_compute_cost_basic_input_output():
    """Pure input + output, multiplier 1.0."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,  # ¥0.015 / 1K
        output_price_micro_yuan=75000,  # ¥0.075 / 1K
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=15000,
        channel_multiplier=1.0,
    )
    # (1*15000 + 1*75000) * 1.0 = 90000 micro-yuan = 9 cents
    assert cost == 9


def test_compute_cost_with_multiplier():
    """channel_multiplier scales the result."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=0,
        output_price_micro_yuan=75000,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=0,
        channel_multiplier=0.5,
    )
    # 1*75000 * 0.5 = 37500 micro-yuan = 3.75 cents → ceil = 4
    assert cost == 4


def test_compute_cost_cache_creation_charged_at_input_price():
    """cache_creation uses its own price param (caller passes input_price)."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=2000,  # 2K cache_creation
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=15000,  # passed explicitly
        channel_multiplier=1.0,
    )
    # 2 * 15000 = 30000 micro-yuan = 3 cents
    assert cost == 3


def test_compute_cost_cache_read_at_own_price():
    """cache_read uses cache_read_price (often 0)."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=5000,
        cache_creation_tokens=0,
        input_price_micro_yuan=0,
        output_price_micro_yuan=0,
        cache_read_price_micro_yuan=3000,  # ¥0.003 / 1K
        cache_creation_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    # 5 * 3000 = 15000 micro-yuan = 1.5 → ceil = 2
    assert cost == 2


def test_compute_cost_zero_tokens_returns_zero():
    """All zero tokens → zero cost."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=75000,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=15000,
        channel_multiplier=1.0,
    )
    assert cost == 0


def test_compute_cost_rounds_up():
    """Fractional cents round up to next whole cent."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=1,  # tiny
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    # 1/1000 * 15000 = 15 micro-yuan = 0.0015 cents → ceil = 1
    assert cost == 1

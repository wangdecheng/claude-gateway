"""Unit tests for the pure apply_coefficient() helper."""

import os
import sys

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)


def test_apply_coefficient_1_returns_same_values():
    """coefficient=1.0 is a fast path; values are returned unchanged."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=10,
        cache_read_tokens=20,
        cache_creation_tokens=30,
        output_tokens=40,
        coefficient=1.0,
    )
    assert out.input_tokens == 10
    assert out.cache_read_tokens == 20
    assert out.cache_creation_tokens == 30
    assert out.output_tokens == 40


def test_apply_coefficient_half_ceil_boundary():
    """7 * 0.5 = 3.5 -> ceil = 4.  8 * 0.5 = 4.0 -> ceil = 4."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=7,
        cache_read_tokens=8,
        cache_creation_tokens=1,
        output_tokens=0,
        coefficient=0.5,
    )
    assert out.input_tokens == 4
    assert out.cache_read_tokens == 4
    assert out.cache_creation_tokens == 1
    assert out.output_tokens == 0


def test_apply_coefficient_third_rounds_up():
    """1 * 0.33 = 0.33 -> ceil = 1."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=1,
        cache_read_tokens=2,
        cache_creation_tokens=3,
        output_tokens=4,
        coefficient=0.33,
    )
    assert out.input_tokens == 1
    assert out.cache_read_tokens == 1
    assert out.cache_creation_tokens == 1
    assert out.output_tokens == 2


def test_apply_coefficient_fields_are_independent():
    """Each field multiplies by the coefficient independently."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=500,
        coefficient=0.5,
    )
    assert out.input_tokens == 500
    assert out.output_tokens == 250


def test_apply_coefficient_zero_inputs_stay_zero():
    """Zero token counts stay zero under any coefficient."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=0,
        coefficient=0.1,
    )
    assert out.input_tokens == 0
    assert out.cache_read_tokens == 0
    assert out.cache_creation_tokens == 0
    assert out.output_tokens == 0

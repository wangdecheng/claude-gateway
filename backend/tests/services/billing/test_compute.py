"""Unit tests for billing compute_cost."""

import os
import sys

import pytest

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
        channel_multiplier=0.5,
    )
    # 1*75000 * 0.5 = 37500 micro-yuan = 3.75 cents → ceil = 4
    assert cost == 4


def test_compute_cost_cache_read_charged_at_one_tenth_input():
    """cache_read is folded into input at 1/10 rate."""
    from app.services.billing.compute import compute_cost

    # 1000 input + 9000 cache_read at 15000 micro-yuan/1K input price.
    # effective_input = 1000 + 9000/10 = 1900
    # base = 1.9 * 15000 + 0 = 28500 micro-yuan = 2.85 cents → ceil = 3
    cost = compute_cost(
        input_tokens=1000,
        output_tokens=0,
        cache_read_tokens=9000,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    assert cost == 3


def test_compute_cost_cache_creation_charged_at_input_rate():
    """cache_creation is charged at the full input rate."""
    from app.services.billing.compute import compute_cost

    # 1000 input + 2000 cache_creation at 15000 micro-yuan/1K.
    # effective_input = 1000 + 2000 + 0 = 3000
    # base = 3 * 15000 = 45000 micro-yuan = 4.5 cents → ceil = 5
    cost = compute_cost(
        input_tokens=1000,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=2000,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    assert cost == 5


def test_compute_cost_combined_cache_creation_and_cache_read():
    """cache_creation at full input rate, cache_read at 1/10 — combined."""
    from app.services.billing.compute import compute_cost

    # 1000 input + 2000 cache_creation + 5000 cache_read at 15000/1K.
    # effective_input = 1000 + 2000 + 5000/10 = 3500
    # base = 3.5 * 15000 = 52500 micro-yuan = 5.25 cents → ceil = 6
    cost = compute_cost(
        input_tokens=1000,
        output_tokens=0,
        cache_read_tokens=5000,
        cache_creation_tokens=2000,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    assert cost == 6


def test_compute_cost_cache_read_only():
    """Only cache_read (no fresh input) still costs 1/10 of input rate."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=10000,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=75000,
        channel_multiplier=1.0,
    )
    # effective_input = 10000/10 = 1000
    # base = 1 * 15000 = 15000 micro-yuan = 1.5 cents → ceil = 2
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
        channel_multiplier=1.0,
    )
    # 1/1000 * 15000 = 15 micro-yuan = 0.0015 cents → ceil = 1
    assert cost == 1


@pytest.mark.asyncio
async def test_compute_costs_for_pending_loads_prices_and_multiplier():
    """compute_costs_for_pending loads channel.multiplier and model prices, calls compute_cost."""
    import os
    import sys
    import uuid
    from datetime import datetime, timezone

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.database import Base
    from app.models.api_key import ApiKey
    from app.models.model import Model
    from app.models.model_provider_route import ModelProviderRoute
    from app.models.pending_billing import PendingBilling
    from app.models.provider import Provider
    from app.models.user import User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Seed with multiplier=0.5 provider (channel multiplier now lives on provider)
        session.add(User(id=1, email="t@e.com", password_hash="x", balance=1000, role="user", status="active"))
        session.add(Provider(id=1, name="p", channel_name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", multiplier=0.5, status="active"))
        session.add(Model(id=1, public_name="m", input_price=15000, output_price=75000, cache_read_price=0, status="active"))
        session.add(ModelProviderRoute(id=1, model_id=1, provider_id=1, provider_model="m", is_default=True, status="active"))
        session.add(ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"))
        await session.flush()
        pb = PendingBilling(
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, route_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
            status="pending",
        )
        session.add(pb)
        await session.commit()

        from app.services.billing.compute import compute_costs_for_pending
        cost = await compute_costs_for_pending(pb, session)
        # (1*15000 + 1*75000) * 0.5 = 45000 micro-yuan = 4.5 → ceil = 5
        assert cost == 5
    await engine.dispose()

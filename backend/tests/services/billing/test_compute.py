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
    from app.models.model import ChannelConfig, Model
    from app.models.pending_billing import PendingBilling
    from app.models.provider import Provider
    from app.models.user import User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Seed with multiplier=0.5 channel
        session.add(User(id=1, email="t@e.com", password_hash="x", balance=1000, role="user", status="active"))
        session.add(Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active"))
        session.add(Model(id=1, public_name="m", input_price=15000, output_price=75000, cache_read_price=0, status="active"))
        session.add(ChannelConfig(id=1, model_id=1, provider_id=1, name="default", provider_model_id="m", multiplier=0.5, is_default=True, status="active"))
        session.add(ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"))
        await session.flush()
        pb = PendingBilling(
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
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

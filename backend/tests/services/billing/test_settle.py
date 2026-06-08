"""Unit tests for settle_one — happy path and failure paths."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)


import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.billing_record import BillingRecord
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.request_log import RequestLog
from app.models.usage import UsageRecord
from app.models.user import User


@pytest.fixture
async def seeded_db():
    """Yield (session, refs) for an in-memory DB with user, model, route seeded."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        user = User(
            id=1,
            email="t@e.com",
            password_hash="x",
            balance=10000,
            role="user",
            status="active",
        )
        provider = Provider(
            id=1,
            name="p",
            channel_name="p",
            api_base_url="http://x",
            auth_header="Authorization",
            adapter="openai-chat-completions",
            status="active",
        )
        model = Model(
            id=1,
            public_name="m",
            input_price=15000,
            output_price=75000,
            cache_read_price=0,
            status="active",
        )
        route = ModelProviderRoute(
            id=1,
            model_id=1,
            provider_id=1,
            provider_model="m",
            is_default=True,
            status="active",
        )
        api_key = ApiKey(
            id=1,
            user_id=1,
            name="k",
            key_prefix="sk-abc",
            key_hash="h",
            status="active",
        )
        session.add_all([user, provider, model, route, api_key])
        await session.commit()
        refs = {
            "user_id": 1,
            "api_key_id": 1,
            "model_id": 1,
            "route_id": 1,
            "provider_id": 1,
        }
        yield session, refs

    await engine.dispose()


@pytest.mark.asyncio
async def test_settle_one_deducts_balance_and_writes_three_tables(seeded_db):
    """Happy path: balance deducted, request_logs/billing_records/usage_records all written, status='settled'."""
    session, refs = seeded_db
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.settle import settle_one

    pb = await write_pending_billing(
        session,
        request_id=uuid.uuid4(),
        user_id=refs["user_id"],
        api_key_id=refs["api_key_id"],
        model_id=refs["model_id"],
        route_id=refs["route_id"],
        provider_id=refs["provider_id"],
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    await session.commit()

    await settle_one(session, pb)
    await session.commit()

    # Balance: started 10000 cents, cost = (15000+75000)/10000 = 9 cents
    user = await session.get(User, 1)
    assert user.balance == 10000 - 9

    # pending_billing marked settled
    await session.refresh(pb)
    assert pb.status == "settled"
    assert pb.settled_at is not None

    # request_logs
    rl_result = await session.execute(
        select(RequestLog).where(RequestLog.request_id == pb.request_id.hex)
    )
    rl = rl_result.scalar_one()
    assert rl.user_id == 1
    assert rl.cost_cents == 9
    assert rl.route_id == 1
    assert rl.status == "success"

    # billing_records (1:1 with request_log)
    br_result = await session.execute(
        select(BillingRecord).where(BillingRecord.request_log_id == rl.id)
    )
    br = br_result.scalar_one()
    assert br.amount_cents == 9
    assert br.balance_after_cents == 10000 - 9

    # usage_records
    ur_result = await session.execute(select(UsageRecord).where(UsageRecord.user_id == 1))
    ur = ur_result.scalar_one()
    assert ur.cost_cents == 9
    assert ur.route_id == 1
    assert ur.input_tokens == 1000


@pytest.mark.asyncio
async def test_settle_one_increments_retry_on_failure(seeded_db):
    """If compute throws, retry_count increments, status stays 'pending'."""
    session, refs = seeded_db
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.settle import settle_one

    pb = await write_pending_billing(
        session,
        request_id=uuid.uuid4(),
        user_id=refs["user_id"],
        api_key_id=refs["api_key_id"],
        model_id=refs["model_id"],
        route_id=refs["route_id"],
        provider_id=refs["provider_id"],
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    await session.commit()

    # Force a failure by deleting the route row
    ch = await session.get(ModelProviderRoute, 1)
    await session.delete(ch)
    await session.commit()

    # Capture the id before rollback (rollback expires in-memory attributes)
    pb_id = pb.id

    # Simulate the worker contract: settle_one raises, caller rolls back
    # and calls mark_retry in a follow-up transaction.
    from app.services.billing.settle import mark_retry

    raised: Exception | None = None
    try:
        await settle_one(session, pb)
    except Exception as exc:
        raised = exc
    assert raised is not None
    await session.rollback()

    # Re-fetch pb in a fresh transaction (rollback expires attributes)
    pb = await session.get(PendingBilling, pb_id)
    assert pb is not None

    await mark_retry(session, pb, raised)
    await session.commit()

    await session.refresh(pb)
    assert pb.retry_count == 1
    assert pb.status == "pending"
    assert pb.last_error is not None

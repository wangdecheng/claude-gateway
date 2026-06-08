"""Unit tests for pending_billing write/claim operations."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)


import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.user import User


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Seed minimal fixtures
        user = User(id=1, email="t@e.com", password_hash="x", balance=1000, role="user", status="active")
        provider = Provider(id=1, name="p", channel_name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active")
        model = Model(id=1, public_name="m", input_price=15000, output_price=75000, status="active")
        route = ModelProviderRoute(id=1, model_id=1, provider_id=1, provider_model="m", is_default=True, status="active")
        api_key = ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active")
        session.add_all([user, provider, model, route, api_key])
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_write_pending_billing_inserts_row(db_session: AsyncSession):
    """write_pending_billing returns a PendingBilling with status='pending' and the right fields."""
    from app.services.billing.pending import write_pending_billing

    request_id = uuid.uuid4()
    pb = await write_pending_billing(
        db_session,
        request_id=request_id,
        user_id=1,
        api_key_id=1,
        model_id=1,
        route_id=1,
        provider_id=1,
        input_tokens=100,
        output_tokens=200,
        cache_read_tokens=50,
        cache_creation_tokens=0,
    )
    await db_session.commit()

    assert isinstance(pb, PendingBilling)
    assert pb.request_id == request_id
    assert pb.status == "pending"
    assert pb.retry_count == 0
    assert pb.input_tokens == 100
    assert pb.output_tokens == 200
    assert pb.cache_read_tokens == 50
    assert pb.last_error is None
    assert pb.settled_at is None


@pytest.mark.asyncio
async def test_write_pending_billing_idempotent_on_request_id(db_session: AsyncSession):
    """Same request_id → raises (UNIQUE violation)."""
    import sqlalchemy.exc
    from app.services.billing.pending import write_pending_billing

    request_id = uuid.uuid4()
    await write_pending_billing(
        db_session,
        request_id=request_id, user_id=1, api_key_id=1,
        model_id=1, route_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    await db_session.commit()
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await write_pending_billing(
            db_session,
            request_id=request_id, user_id=1, api_key_id=1,
            model_id=1, route_id=1, provider_id=1,
            input_tokens=10, output_tokens=10,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_claim_pending_batch_returns_only_old_pending(db_session: AsyncSession):
    """claim_pending_batch skips recent pending rows (in-flight window)."""
    from app.services.billing.pending import claim_pending_batch, write_pending_billing

    # Recent row (created_at = now) — should be SKIPPED
    await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, route_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    await db_session.commit()

    claimed = await claim_pending_batch(db_session, max_age_seconds=5, limit=10)
    assert claimed == []


@pytest.mark.asyncio
async def test_claim_pending_batch_returns_old_pending(db_session: AsyncSession):
    """claim_pending_batch returns rows older than max_age."""
    from app.services.billing.pending import claim_pending_batch, write_pending_billing

    pb = await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, route_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    # Backdate created_at to 10s ago
    pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await db_session.commit()

    claimed = await claim_pending_batch(db_session, max_age_seconds=5, limit=10)
    assert len(claimed) == 1
    assert claimed[0].id == pb.id


@pytest.mark.asyncio
async def test_claim_pending_batch_skips_settled_and_dead(db_session: AsyncSession):
    """Only status='pending' rows are claimed."""
    from app.services.billing.pending import claim_pending_batch, write_pending_billing

    # Insert one pending + one settled
    pb_pending = await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, route_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    pb_settled = await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, route_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    pb_pending.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    pb_settled.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    pb_settled.status = "settled"
    await db_session.commit()

    claimed = await claim_pending_batch(db_session, max_age_seconds=5, limit=10)
    assert len(claimed) == 1
    assert claimed[0].id == pb_pending.id

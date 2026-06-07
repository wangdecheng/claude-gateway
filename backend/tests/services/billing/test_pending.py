"""Unit tests for pending_billing write/claim operations."""

import os
import sys
import uuid

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)


import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
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
        provider = Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active")
        model = Model(id=1, public_name="m", input_price=15000, output_price=75000, status="active")
        channel = ChannelConfig(id=1, model_id=1, provider_id=1, name="default", provider_model_id="m", multiplier=1.0, is_default=True, status="active")
        api_key = ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active")
        session.add_all([user, provider, model, channel, api_key])
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
        channel_id=1,
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
        model_id=1, channel_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    await db_session.commit()
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await write_pending_billing(
            db_session,
            request_id=request_id, user_id=1, api_key_id=1,
            model_id=1, channel_id=1, provider_id=1,
            input_tokens=10, output_tokens=10,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        await db_session.commit()

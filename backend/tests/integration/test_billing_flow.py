"""End-to-end billing flow: proxy stream → pending_billings → worker settle."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _BACKEND)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.usage import UsageRecord
from app.models.user import User


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all([
            User(id=1, email="t@e.com", password_hash="x", balance=10000, role="user", status="active"),
            Provider(id=1, name="p", channel_name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active"),
            Model(id=1, public_name="claude-opus-4-8", input_price=15000, output_price=75000, cache_read_price=0, status="active"),
            ChannelConfig(id=1, model_id=1, provider_id=1, name="default", provider_model_id="m", multiplier=0.5, is_default=True, status="active"),
            ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_flow_stream_writes_pending_then_worker_settles(session_factory):
    """Insert pending_billing (simulating proxy stream-end), worker settles, balance deducted, multiplier applied."""
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        pb = await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=2000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        # Backdate to bypass in-flight window
        pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 1

    async with session_factory() as session:
        # Balance: 10000 - cost
        # cost = (2000/1000 * 15000 + 1000/1000 * 75000) * 0.5
        #      = (30000 + 75000) * 0.5 = 52500 micro-yuan = 5.25 cents → ceil = 6
        u = await session.get(User, 1)
        assert u.balance == 10000 - 6

        pbs = (await session.execute(select(PendingBilling))).scalars().all()
        assert pbs[0].status == "settled"

        urs = (await session.execute(select(UsageRecord).where(UsageRecord.user_id == 1))).scalars().all()
        assert len(urs) == 1
        assert urs[0].channel_id == 1
        assert urs[0].cost_cents == 6
        assert urs[0].input_tokens == 2000
        assert urs[0].output_tokens == 1000

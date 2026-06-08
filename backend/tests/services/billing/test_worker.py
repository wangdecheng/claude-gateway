"""Unit tests for BillingWorker."""

import asyncio
import os
import sys
import uuid

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.user import User
from app.models.usage import UsageRecord


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
            Model(id=1, public_name="m", input_price=15000, output_price=75000, cache_read_price=0, status="active"),
            ChannelConfig(id=1, model_id=1, provider_id=1, name="default", provider_model_id="m", multiplier=1.0, is_default=True, status="active"),
            ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_and_settle_processes_old_pending(session_factory):
    """A pending row older than max_age gets settled by _scan_and_settle."""
    from datetime import datetime, timedelta, timezone
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        pb = await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 1

    async with session_factory() as session:
        u = await session.get(User, 1)
        assert u.balance == 10000 - 9  # cost 9 cents
        pbs = (await session.execute(select(PendingBilling))).scalars().all()
        assert pbs[0].status == "settled"


@pytest.mark.asyncio
async def test_scan_and_settle_skips_recent_pending(session_factory):
    """A pending row newer than max_age is skipped."""
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 0


@pytest.mark.asyncio
async def test_scan_and_settle_marks_dead_after_max_retry(session_factory):
    """A row whose settle fails max_retry+1 times is marked 'dead'."""
    from datetime import datetime, timedelta, timezone
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        pb = await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        # Pre-bump retry_count past max
        await session.execute(
            __import__("sqlalchemy").update(PendingBilling).where(PendingBilling.id == pb.id).values(retry_count=3)
        )
        # Delete the channel to force a failure on settle
        ch = await session.get(ChannelConfig, 1)
        await session.delete(ch)
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 0  # couldn't settle

    async with session_factory() as session:
        pbs = (await session.execute(select(PendingBilling))).scalars().all()
        assert pbs[0].status == "dead"

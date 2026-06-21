"""Tests for scripts/cleanup_old_records.py.

Uses an in-memory SQLite engine to verify each retention rule plus
idempotency and the dry-run mode. The script under test talks directly
to the DB (no app state involvement), so the test engine is independent
of the FastAPI app fixtures.
"""

import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure the backend/ directory is on sys.path so `app.*` imports resolve,
# matching the pattern used in every other tests/ module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.database import Base
from app.models.billing_record import BillingRecord
from app.models.pending_billing import PendingBilling
from app.models.redemption_code import RedemptionCode
from app.models.request_log import RequestLog
from app.models.usage import UsageRecord
from app.models.user import User  # noqa: I001  (import order is intentional)

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
async def engine():
    """In-memory SQLite engine; tables created on demand."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as s:
        yield s


@pytest.fixture
def cleanup_module(monkeypatch) -> ModuleType:
    """Import the cleanup script with its `os.environ` defaults preserved.

    The script reads CLEANUP_*_DAYS env vars at import time, so we set
    any test-specific overrides BEFORE importing. Reload the module
    between tests that need different env.
    """
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    import scripts.cleanup_old_records as mod

    importlib.reload(mod)
    return mod


# ── Helpers ────────────────────────────────────────────────────────────


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _make_user(session: AsyncSession) -> User:
    u = User(
        email=f"u{os.urandom(3).hex()}@x.io",
        password_hash="x",
    )
    session.add(u)
    await session.flush()
    return u


async def _make_request_log(session: AsyncSession, user_id: int, when: datetime) -> int:
    rl = RequestLog(
        request_id=os.urandom(16).hex(),
        user_id=user_id,
        sk_id=1,
        model_id=1,
        route_id=1,
        provider_id=1,
        input_tokens=10,
        output_tokens=5,
        cost_cents=1,
        status="success",
        created_at=when,
    )
    session.add(rl)
    await session.flush()
    return rl.id


async def _make_billing_record(
    session: AsyncSession, user_id: int, request_log_id: int, when: datetime
) -> None:
    session.add(
        BillingRecord(
            user_id=user_id,
            request_log_id=request_log_id,
            amount_cents=1,
            balance_after_cents=99,
            created_at=when,
        )
    )


async def _make_usage(session: AsyncSession, user_id: int, when: datetime) -> None:
    session.add(
        UsageRecord(
            user_id=user_id,
            api_key_id=1,
            model="m",
            input_tokens=1,
            output_tokens=1,
            cost_cents=1,
            created_at=when,
        )
    )


async def _make_pending(
    session: AsyncSession, user_id: int, when: datetime, status: str = "pending"
) -> None:
    pb = PendingBilling(
        request_id=os.urandom(16).hex(),
        user_id=user_id,
        api_key_id=1,
        model_id=1,
        route_id=1,
        provider_id=1,
        status=status,
        created_at=when,
    )
    if status in ("settled", "dead"):
        pb.settled_at = when
    session.add(pb)


async def _make_redemption(
    session: AsyncSession,
    *,
    status: str,
    expires_at: datetime,
) -> None:
    session.add(
        RedemptionCode(
            code_hash=os.urandom(8).hex(),
            code_prefix="REDM",
            amount=100,
            status=status,
            expires_at=expires_at,
        )
    )


# ── request_logs ───────────────────────────────────────────────────────


async def test_request_logs_older_than_retention_deleted(engine, session, cleanup_module):
    user = await _make_user(session)
    rid = await _make_request_log(session, user.id, _ago(200))  # > 180d
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(RequestLog))).scalars().all()
    assert all(r.id != rid for r in remaining), (
        "old request_log with no billing_record should be deleted"
    )


async def test_request_logs_with_billing_record_kept(engine, session, cleanup_module):
    """request_log that has a billing_record pointing at it must NOT be deleted,
    even if past retention — deleting it would violate the FK on billing_records
    (no ON DELETE CASCADE defined)."""
    user = await _make_user(session)
    rid = await _make_request_log(session, user.id, _ago(200))
    await _make_billing_record(session, user.id, rid, _ago(200))
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    still = (await session.execute(_select_all(RequestLog))).scalars().all()
    assert any(r.id == rid for r in still), "request_log with billing_record must be kept (FK)"


async def test_recent_request_logs_kept(engine, session, cleanup_module):
    user = await _make_user(session)
    rid = await _make_request_log(session, user.id, _ago(10))  # recent
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    still = (await session.execute(_select_all(RequestLog))).scalars().all()
    assert any(r.id == rid for r in still)


# ── usage_records ──────────────────────────────────────────────────────


async def test_usage_records_older_than_retention_deleted(engine, session, cleanup_module):
    user = await _make_user(session)
    await _make_usage(session, user.id, _ago(120))  # > 90d
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(UsageRecord))).scalars().all()
    assert remaining == []


async def test_usage_records_within_retention_kept(engine, session, cleanup_module):
    user = await _make_user(session)
    await _make_usage(session, user.id, _ago(10))
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(UsageRecord))).scalars().all()
    assert len(remaining) == 1


# ── pending_billings ───────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["pending", "settled"])
async def test_non_dead_pending_billings_kept(engine, session, cleanup_module, status):
    user = await _make_user(session)
    await _make_pending(session, user.id, _ago(60), status=status)
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(PendingBilling))).scalars().all()
    assert len(remaining) == 1, f"status={status} must be kept"


async def test_dead_pending_billings_past_grace_deleted(engine, session, cleanup_module):
    user = await _make_user(session)
    await _make_pending(session, user.id, _ago(60), status="dead")  # > 7d
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(PendingBilling))).scalars().all()
    assert remaining == []


async def test_dead_pending_billings_within_grace_kept(engine, session, cleanup_module):
    user = await _make_user(session)
    await _make_pending(session, user.id, _ago(2), status="dead")  # < 7d
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(PendingBilling))).scalars().all()
    assert len(remaining) == 1


# ── redemption_codes ───────────────────────────────────────────────────


async def test_expired_issued_redemption_past_grace_deleted(engine, session, cleanup_module):
    await _make_redemption(session, status="issued", expires_at=_ago(30))  # 30d past expiry
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(RedemptionCode))).scalars().all()
    assert remaining == []


async def test_expired_issued_redemption_within_grace_kept(engine, session, cleanup_module):
    await _make_redemption(session, status="issued", expires_at=_ago(2))  # 2d past expiry
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(RedemptionCode))).scalars().all()
    assert len(remaining) == 1


async def test_used_redemption_kept_forever(engine, session, cleanup_module):
    await _make_redemption(session, status="used", expires_at=_ago(365))
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await cleanup_module.cleanup(db)

    remaining = (await session.execute(_select_all(RedemptionCode))).scalars().all()
    assert len(remaining) == 1, "used codes are the audit trail and must not be deleted"


# ── idempotency + dry-run ──────────────────────────────────────────────


async def test_cleanup_is_idempotent(engine, session, cleanup_module):
    user = await _make_user(session)
    await _make_usage(session, user.id, _ago(120))
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        first = await cleanup_module.cleanup(db)
    async with Session() as db:
        second = await cleanup_module.cleanup(db)

    assert first["usage_records"] == 1
    assert second["usage_records"] == 0, "second run must be a no-op"


async def test_dry_run_does_not_commit(engine, session, cleanup_module):
    user = await _make_user(session)
    await _make_usage(session, user.id, _ago(120))
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        summary = await cleanup_module.cleanup(db, dry_run=True)

    assert summary["usage_records"] == 0, "dry-run must not report deletes"
    remaining = (await session.execute(_select_all(UsageRecord))).scalars().all()
    assert len(remaining) == 1, "dry-run must not commit deletes"


# ── env var overrides ──────────────────────────────────────────────────


async def test_env_var_shortens_retention(monkeypatch, engine, session):
    """CLEANUP_USAGE_RECORD_DAYS=10 — rows 30d old should now be deleted."""
    monkeypatch.setenv("CLEANUP_USAGE_RECORD_DAYS", "10")
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    import scripts.cleanup_old_records as mod

    importlib.reload(mod)

    user = await _make_user(session)
    await _make_usage(session, user.id, _ago(30))
    await session.commit()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # noqa: N806
    async with Session() as db:
        await mod.cleanup(db)

    remaining = (await session.execute(_select_all(UsageRecord))).scalars().all()
    assert remaining == []


# ── helpers ────────────────────────────────────────────────────────────


def _select_all(model):
    return select(model)

"""Tests for admin redemption-code generation."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.exceptions import AppException
from server import app


@pytest.fixture(autouse=True)
async def setup_db():
    """Create in-memory SQLite engine + users and attach it to app state."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    async with session_factory() as session:
        session.add_all(
            [
                User(
                    id=1,
                    email="admin@example.com",
                    password_hash="unused",
                    balance=0,
                    role="admin",
                    status="active",
                ),
                User(
                    id=2,
                    email="user@example.com",
                    password_hash="unused",
                    balance=100,
                    role="user",
                    status="active",
                ),
            ]
        )
        await session.commit()

    yield

    app.dependency_overrides.clear()
    await engine.dispose()
    del app.state.db_session_factory
    del app.state.db_engine


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _admin_user() -> User:
    return User(
        id=1,
        email="admin@example.com",
        password_hash="unused",
        balance=0,
        role="admin",
        status="active",
    )


def _regular_user() -> User:
    return User(
        id=2,
        email="user@example.com",
        password_hash="unused",
        balance=100,
        role="user",
        status="active",
    )


def _override_admin_auth() -> None:
    from app.dependencies import get_current_admin

    async def _mock_admin():
        return _admin_user()

    app.dependency_overrides[get_current_admin] = _mock_admin


def _override_user_auth() -> None:
    from app.dependencies import get_current_user

    async def _mock_user():
        return _regular_user()

    app.dependency_overrides[get_current_user] = _mock_user


def _override_forbidden_admin_auth() -> None:
    from app.dependencies import get_current_admin

    async def _mock_forbidden():
        raise AppException(status_code=403, error="权限不足，需要管理员权限", code="FORBIDDEN")

    app.dependency_overrides[get_current_admin] = _mock_forbidden


@pytest.mark.asyncio
async def test_admin_can_create_redemption_code():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/redemption",
            json={"amount": 1234},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["code"].startswith("REDM-")
    assert data["codePrefix"] == data["code"][:9]
    assert data["amount"] == 1234
    assert data["status"] == "issued"
    assert data["expiresAt"]
    assert data["createdAt"]


@pytest.mark.asyncio
async def test_admin_redemption_defaults_to_five_days():
    _override_admin_auth()
    now = datetime.now(timezone.utc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/redemption",
            json={"amount": 100},
        )

    assert resp.status_code == 200, resp.text
    expires_at = _parse_iso(resp.json()["expiresAt"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(days=4, hours=23) <= expires_at - now <= timedelta(days=5, minutes=1)


@pytest.mark.asyncio
async def test_regular_user_cannot_create_redemption_code():
    _override_forbidden_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/redemption",
            json={"amount": 100},
        )

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_admin_redemption_rejects_invalid_amount():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/redemption",
            json={"amount": 0},
        )

    assert resp.status_code in {400, 422}


@pytest.mark.asyncio
async def test_generated_redemption_code_can_be_redeemed():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/admin/redemption",
            json={"amount": 500},
        )
        assert create_resp.status_code == 200, create_resp.text

        app.dependency_overrides.clear()
        _override_user_auth()
        redeem_resp = await client.post(
            "/api/redeem",
            json={"code": create_resp.json()["code"]},
        )

    assert redeem_resp.status_code == 200, redeem_resp.text
    assert redeem_resp.json()["amount"] == 500

    async with app.state.db_session_factory() as session:
        user = (await session.execute(select(User).where(User.id == 2))).scalar_one()
        assert user.balance == 600

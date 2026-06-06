"""Tests for admin user management endpoints."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from server import app


@pytest.fixture(autouse=True)
async def setup_db():
    """Create in-memory SQLite engine + tables and attach to app state."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    yield

    await engine.dispose()
    del app.state.db_session_factory
    del app.state.db_engine


@pytest.fixture(autouse=True)
def override_admin_auth():
    """Replace get_current_admin with a stable admin user."""
    from app.dependencies import get_current_admin

    async def _mock_admin():
        return User(
            id=1,
            email="admin@example.com",
            password_hash="unused",
            balance=0,
            role="admin",
            status="active",
        )

    original = app.dependency_overrides.get(get_current_admin)
    app.dependency_overrides[get_current_admin] = _mock_admin
    yield
    if original is None:
        app.dependency_overrides.pop(get_current_admin, None)
    else:
        app.dependency_overrides[get_current_admin] = original


async def _seed_users() -> None:
    async with app.state.db_session_factory() as session:
        session.add_all(
            [
                User(
                    id=1,
                    email="admin@example.com",
                    password_hash="admin-hash",
                    balance=500,
                    role="admin",
                    status="active",
                ),
                User(
                    id=2,
                    email="user@example.com",
                    password_hash="user-hash",
                    balance=1234,
                    role="user",
                    status="active",
                ),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_admin_users_excludes_password_hash():
    await _seed_users()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/users")

    assert resp.status_code == 200, resp.text
    users = resp.json()
    assert [user["email"] for user in users] == ["admin@example.com", "user@example.com"]
    assert users[1]["balance"] == 1234
    assert users[1]["role"] == "user"
    assert users[1]["status"] == "active"
    assert "createdAt" in users[1]
    assert "password_hash" not in users[1]
    assert "passwordHash" not in users[1]


@pytest.mark.asyncio
async def test_toggle_user_status_disables_and_enables_regular_user():
    await _seed_users()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        disable_resp = await client.patch("/api/admin/users/2/status")
        enable_resp = await client.patch("/api/admin/users/2/status")

    assert disable_resp.status_code == 200, disable_resp.text
    assert disable_resp.json()["status"] == "disabled"
    assert enable_resp.status_code == 200, enable_resp.text
    assert enable_resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_admin_cannot_disable_self():
    await _seed_users()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.patch("/api/admin/users/1/status")

    assert resp.status_code == 400
    assert resp.json()["code"] == "CANNOT_DISABLE_SELF"

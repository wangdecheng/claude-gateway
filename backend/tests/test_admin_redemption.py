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
from app.exceptions import AppException
from app.models.redemption_code import RedemptionCode
from app.models.user import User
from app.services.redemption_service import hash_code
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


@pytest.mark.asyncio
async def test_admin_can_list_redemption_codes_newest_first():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/admin/redemption", json={"amount": 100})
        second = await client.post("/api/admin/redemption", json={"amount": 200})
        third = await client.post("/api/admin/redemption", json={"amount": 300})
        list_resp = await client.get("/api/admin/redemption")

    assert all(r.status_code == 200 for r in (first, second, third))
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert len(items) == 3
    # newest first
    assert items[0]["amount"] == 300
    assert items[1]["amount"] == 200
    assert items[2]["amount"] == 100
    # newly created codes are issued and not yet used
    assert items[0]["status"] == "issued"
    assert items[0]["codePrefix"].startswith("REDM-")
    assert items[0]["createdByEmail"] == "admin@example.com"
    assert items[0]["usedByEmail"] is None
    assert items[0]["usedAt"] is None


@pytest.mark.asyncio
async def test_admin_list_marks_status_used_after_redemption():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/admin/redemption", json={"amount": 500})
        assert create_resp.status_code == 200, create_resp.text
        raw_code = create_resp.json()["code"]

        app.dependency_overrides.clear()
        _override_user_auth()
        redeem_resp = await client.post("/api/redeem", json={"code": raw_code})
        assert redeem_resp.status_code == 200, redeem_resp.text

        app.dependency_overrides.clear()
        _override_admin_auth()
        list_resp = await client.get("/api/admin/redemption")

    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["status"] == "used"
    assert items[0]["usedByEmail"] == "user@example.com"
    assert items[0]["usedAt"] is not None


@pytest.mark.asyncio
async def test_admin_list_reports_expired_for_past_due_issued_codes():
    """A row still stored as 'issued' but past expires_at should surface as 'expired'."""
    # Insert directly via ORM so we control expires_at
    async with app.state.db_session_factory() as session:
        session.add(
            RedemptionCode(
                code_hash=hash_code("REDM-EXPI-RED1-TEST"),
                code_prefix="REDM-EXPI",
                amount=400,
                status="issued",
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                created_by=1,
            )
        )
        await session.commit()

    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_resp = await client.get("/api/admin/redemption")

    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["status"] == "expired"

    # DB row itself stays 'issued' (read-only endpoint)
    async with app.state.db_session_factory() as session:
        row = (await session.execute(select(RedemptionCode))).scalar_one()
        assert row.status == "issued"


@pytest.mark.asyncio
async def test_admin_list_filters_by_effective_status():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/admin/redemption", json={"amount": 100})
        await client.post("/api/admin/redemption", json={"amount": 200})

    # Also insert one already-expired
    async with app.state.db_session_factory() as session:
        session.add(
            RedemptionCode(
                code_hash=hash_code("REDM-EXPI-RED2-TEST"),
                code_prefix="REDM-EXP2",
                amount=999,
                status="issued",
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                created_by=1,
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        issued_resp = await client.get("/api/admin/redemption", params={"status": "issued"})
        expired_resp = await client.get("/api/admin/redemption", params={"status": "expired"})

    assert issued_resp.status_code == 200
    assert {item["amount"] for item in issued_resp.json()} == {100, 200}
    assert expired_resp.status_code == 200
    expired_items = expired_resp.json()
    assert len(expired_items) == 1
    assert expired_items[0]["amount"] == 999


@pytest.mark.asyncio
async def test_admin_list_rejects_invalid_status_filter():
    _override_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/redemption", params={"status": "bogus"})

    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_STATUS_FILTER"


@pytest.mark.asyncio
async def test_regular_user_cannot_list_redemption_codes():
    _override_forbidden_admin_auth()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/redemption")

    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"

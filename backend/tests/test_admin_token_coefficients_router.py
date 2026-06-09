"""Integration tests for the admin /api/admin/token-coefficients endpoints."""

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.model import Model
from app.models.token_coefficient import TokenCoefficientConfig
from app.models.user import User
from app.services.token_coefficient_service import TokenCoefficientService
from server import app


@pytest.fixture(autouse=True)
async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    async with session_factory() as session:
        session.add_all([
            User(id=1, email="admin@example.com", password_hash="x",
                 balance=0, role="admin", status="active"),
            Model(id=1, public_name="m1", input_price=0, output_price=0, status="active"),
            Model(id=2, public_name="m2", input_price=0, output_price=0, status="active"),
            TokenCoefficientConfig(scope_type="global", coefficient=1.0),
        ])
        await session.commit()

    # Attach the service the router depends on
    app.state.token_coefficient_service = TokenCoefficientService(session_factory)
    await app.state.token_coefficient_service.load()

    # Auth override: pretend every request is admin id=1
    from app.dependencies import get_current_admin
    async def _admin_override():
        return User(id=1, email="admin@example.com", password_hash="x",
                    balance=0, role="admin", status="active")
    app.dependency_overrides[get_current_admin] = _admin_override

    yield

    app.dependency_overrides.clear()
    await engine.dispose()
    del app.state.token_coefficient_service


@pytest.mark.asyncio
async def test_get_overview_returns_global_and_empty_overrides():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/admin/token-coefficients")
    assert r.status_code == 200
    data = r.json()
    assert data["globalCoefficient"] == 1.0
    assert data["overrides"] == []


@pytest.mark.asyncio
async def test_put_global_validates_coefficient():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 0.5},
        )
        assert r.status_code == 200
        assert r.json()["coefficient"] == 0.5

        # invalid: 0
        r2 = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 0},
        )
        assert r2.status_code == 422

        # invalid: > 1
        r3 = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 1.5},
        )
        assert r3.status_code == 422


@pytest.mark.asyncio
async def test_put_global_invalidates_cache():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # before
        assert app.state.token_coefficient_service.get_for_model(1) == 1.0
        # write
        r = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 0.7},
        )
        assert r.status_code == 200
        # cache should have been invalidated and reloaded
        assert app.state.token_coefficient_service.get_for_model(1) == 0.7


@pytest.mark.asyncio
async def test_upsert_model_creates_then_updates_override():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.3},
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["modelId"] == 1
        assert body1["coefficient"] == 0.3

        # second call updates
        r2 = await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.4},
        )
        assert r2.status_code == 200
        assert r2.json()["coefficient"] == 0.4

        # cache reflects update
        assert app.state.token_coefficient_service.get_for_model(1) == 0.4
        assert app.state.token_coefficient_service.get_for_model(2) == 1.0  # global


@pytest.mark.asyncio
async def test_upsert_model_404_for_unknown_model():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/admin/token-coefficients/models/999",
            json={"coefficient": 0.5},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_model_override_removes_it():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.3},
        )
        assert app.state.token_coefficient_service.get_for_model(1) == 0.3

        r = await ac.delete("/api/admin/token-coefficients/models/1")
        assert r.status_code == 204

        # falls back to global (1.0)
        assert app.state.token_coefficient_service.get_for_model(1) == 1.0


@pytest.mark.asyncio
async def test_get_overview_lists_overrides():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.3},
        )
        r = await ac.get("/api/admin/token-coefficients")
        assert r.status_code == 200
        data = r.json()
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["modelId"] == 1
        assert data["overrides"][0]["coefficient"] == 0.3

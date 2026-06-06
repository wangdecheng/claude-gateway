"""Compatibility tests for Anthropic-style API key headers."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from api.dependencies import require_api_key
from app.database import Base
from app.models.api_key import ApiKey
from app.models.user import User
from app.services.api_key_service import hash_key
from server import app

RAW_KEY = "sk-" + "a" * 40


@pytest.fixture(autouse=True)
async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    async with session_factory() as db:
        user = User(
            email="compat@example.com",
            password_hash="unused",
            balance=10_000,
            role="user",
            status="active",
        )
        db.add(user)
        await db.flush()
        db.add(
            ApiKey(
                user_id=user.id,
                name="compat",
                key_prefix=RAW_KEY[:10],
                key_hash=hash_key(RAW_KEY),
                status="active",
            )
        )
        await db.commit()

    yield

    await engine.dispose()
    del app.state.db_session_factory
    del app.state.db_engine


@pytest.mark.asyncio
async def test_anthropic_auth_token_header_is_accepted():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/models", headers={"anthropic-auth-token": RAW_KEY})

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_key_with_appended_model_suffix_is_accepted():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {RAW_KEY}:claude-opus-4-8"},
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_root_head_probe_is_accepted_without_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.head("/")

    assert resp.status_code == 204
    assert resp.headers["allow"] == "GET, HEAD, OPTIONS"


@pytest.mark.asyncio
async def test_health_head_probe_is_accepted_without_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.head("/health")

    assert resp.status_code == 204
    assert resp.headers["allow"] == "GET, HEAD, OPTIONS"


@pytest.mark.asyncio
async def test_auth_does_not_touch_api_key_last_used_in_request_session():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/models",
            "headers": [(b"anthropic-auth-token", RAW_KEY.encode("utf-8"))],
            "app": app,
        }
    )

    async with app.state.db_session_factory() as db:
        _user, api_key = await require_api_key(request, db=db)

        assert api_key.last_used_at is None

        persisted = (
            await db.execute(select(ApiKey).where(ApiKey.id == api_key.id))
        ).scalar_one()
        assert persisted.last_used_at is None

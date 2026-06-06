"""Tests for admin delete endpoints (model, provider, channel).

Sets up an in-memory SQLite database and uses FastAPI dependency_overrides
to bypass admin authentication.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server import app
from app.database import Base
from app.models.user import User


# ── Database setup fixture ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def setup_db():
    """Create in-memory SQLite engine + tables and attach to app state."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    yield

    await engine.dispose()
    del app.state.db_session_factory
    del app.state.db_engine


# ── Auth bypass fixture ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def override_admin_auth():
    """Replace get_current_admin with a no-op that returns a mock admin user."""
    from app.dependencies import get_current_admin

    async def _mock_admin():
        return User(
            id=1,
            email="test_admin@local",
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


# ── Helper ──────────────────────────────────────────────────────────────


async def _setup_test_data(client: AsyncClient) -> dict:
    """Create a provider, model, and channel for delete testing.

    Model and channel are now created separately — models no longer carry
    provider info or auto-create channels.

    Returns dict with {provider_id, model_id, channel_id}.
    """
    # Create provider
    resp = await client.post(
        "/api/admin/providers",
        json={
            "name": "Test Provider Delete",
            "apiBaseUrl": "https://test.example.com/v1",
            "adapter": "openai-chat-completions",
            "keys": ["sk-test-key-12345678"],
        },
    )
    assert resp.status_code == 201, f"Provider create failed: {resp.text}"
    provider_id = resp.json()["id"]

    # Create model (no provider dependency)
    resp = await client.post(
        "/api/admin/models",
        json={
            "publicName": "Test Model Delete",
            "inputPrice": 10000,
            "outputPrice": 20000,
        },
    )
    assert resp.status_code == 201, f"Model create failed: {resp.text}"
    model_id = resp.json()["id"]

    # Create channel separately (with provider_model_id)
    resp = await client.post(
        "/api/admin/channels",
        json={
            "modelId": model_id,
            "providerId": provider_id,
            "providerModelId": "test-model-delete",
            "multiplier": 1.0,
            "isDefault": True,
        },
    )
    assert resp.status_code == 201, f"Channel create failed: {resp.text}"
    channel_id = resp.json()["id"]

    return {"provider_id": provider_id, "model_id": model_id, "channel_id": channel_id}


# ── Model Delete Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_model_success_hard():
    """Delete a model with no RequestLog references → hard delete.

    Must delete channel first (otherwise blocked by dependents).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        # Delete channel first to unblock model
        await client.delete(f"/api/admin/channels/{data['channel_id']}")

        resp = await client.delete(f"/api/admin/models/{data['model_id']}")
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        body = resp.json()
        assert body["deleted"] is True
        assert body["method"] == "hard"
        assert body["id"] == data["model_id"]

        # Verify it's gone from admin list
        list_resp = await client.get("/api/admin/models")
        ids = [m["id"] for m in list_resp.json()]
        assert data["model_id"] not in ids


@pytest.mark.asyncio
async def test_delete_model_not_found():
    """Deleting a non-existent model returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/admin/models/99999")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_model_blocked_by_channels():
    """Cannot delete a model that still has channel configs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        resp = await client.delete(f"/api/admin/models/{data['model_id']}")
        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == "HAS_DEPENDENTS"


# ── Provider Delete Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_provider_blocked_by_channels():
    """Cannot delete a provider that still has channel configs referencing it."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        resp = await client.delete(f"/api/admin/providers/{data['provider_id']}")
        assert resp.status_code == 409
        assert resp.json()["code"] == "HAS_DEPENDENTS"


@pytest.mark.asyncio
async def test_delete_provider_success_after_cleanup():
    """Can delete a provider after models, channels, and keys are removed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        # Delete channel first
        await client.delete(f"/api/admin/channels/{data['channel_id']}")
        # Delete model
        await client.delete(f"/api/admin/models/{data['model_id']}")

        # Revoke the active key
        keys_resp = await client.get(
            f"/api/admin/providers/{data['provider_id']}/keys"
        )
        for key in keys_resp.json():
            if key["status"] == "active":
                await client.delete(
                    f"/api/admin/providers/{data['provider_id']}/keys/{key['id']}"
                )

        # Now delete provider
        resp = await client.delete(
            f"/api/admin/providers/{data['provider_id']}"
        )
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        assert resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_delete_provider_not_found():
    """Deleting a non-existent provider returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/admin/providers/99999")
        assert resp.status_code == 404


# ── Channel Delete Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_channel_success_hard():
    """Delete a channel with no RequestLog references → hard delete."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        resp = await client.delete(f"/api/admin/channels/{data['channel_id']}")
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        body = resp.json()
        assert body["deleted"] is True
        assert body["method"] == "hard"

        # Verify it's gone from list
        list_resp = await client.get("/api/admin/channels")
        ids = [c["id"] for c in list_resp.json()]
        assert data["channel_id"] not in ids


@pytest.mark.asyncio
async def test_delete_channel_not_found():
    """Deleting a non-existent channel returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/admin/channels/99999")
        assert resp.status_code == 404

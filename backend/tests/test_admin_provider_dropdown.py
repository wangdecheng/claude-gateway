"""Tests for GET /api/admin/providers/dropdown.

Covers the regression where the dropdown:
  - returned only `id`+`name`, so multiple providers sharing the same adapter
    `name` (e.g. two `GLM` upstreams) were indistinguishable; and
  - did not filter `status='deleted'`, so deleted providers showed up as
    ghost/duplicate entries.

Reuses the in-memory SQLite + auth-bypass setup from test_admin_delete.py.
"""

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


async def _create_provider(client: AsyncClient, *, name: str, channel_name: str) -> int:
    resp = await client.post(
        "/api/admin/providers",
        json={
            "name": name,
            "channelName": channel_name,
            "multiplier": 1.0,
            "apiBaseUrl": f"https://{channel_name}.example.com/v1",
            "adapter": "anthropic-messages",
            "keys": ["sk-test-key-12345678"],
        },
    )
    assert resp.status_code == 201, f"Provider create failed: {resp.text}"
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_dropdown_excludes_deleted_providers():
    """Deleted providers must not appear in the dropdown."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        active_id = await _create_provider(client, name="GLM", channel_name="官方")
        deleted_id = await _create_provider(client, name="GLM", channel_name="火山")

        # Soft-delete the second one (revoke key first so delete is allowed).
        keys_resp = await client.get(f"/api/admin/providers/{deleted_id}/keys")
        for key in keys_resp.json():
            if key["status"] == "active":
                await client.delete(f"/api/admin/providers/{deleted_id}/keys/{key['id']}")
        del_resp = await client.delete(f"/api/admin/providers/{deleted_id}")
        assert del_resp.status_code == 200

        resp = await client.get("/api/admin/providers/dropdown")
        assert resp.status_code == 200
        items = resp.json()
        ids = [it["id"] for it in items]
        assert active_id in ids
        assert deleted_id not in ids


@pytest.mark.asyncio
async def test_dropdown_returns_channel_name_for_disambiguation():
    """Each dropdown item carries `channelName` so same-`name` providers differ."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _create_provider(client, name="GLM", channel_name="官方")
        await _create_provider(client, name="GLM", channel_name="火山")

        resp = await client.get("/api/admin/providers/dropdown")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        channel_names = {it["channelName"] for it in items}
        assert channel_names == {"官方", "火山"}
        # `name` is still present (adapter type label)
        assert all(it["name"] == "GLM" for it in items)

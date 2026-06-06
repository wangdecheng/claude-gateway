import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
from httpx import ASGITransport, AsyncClient

from config.settings import get_settings
from server import app


@pytest.fixture(autouse=True)
def override_public_url():
    """Override PUBLIC_URL for test consistency."""
    original = get_settings()
    original.public_url = "https://gateway.example.com"
    app.dependency_overrides[get_settings] = lambda: original
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_public_url_returns_configured_url():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/public-url")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"baseUrl": "https://gateway.example.com"}


@pytest.mark.asyncio
async def test_public_url_no_auth_required():
    """Public URL endpoint should not require authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/public-url")
    assert resp.status_code == 200

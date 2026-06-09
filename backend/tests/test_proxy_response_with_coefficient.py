"""End-to-end test: coefficient is applied to SSE response and to PendingBilling."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider, ProviderKey
from app.models.token_coefficient import TokenCoefficientConfig
from app.models.user import User
from app.services.provider_service import encrypt_api_key
from app.services.token_coefficient_service import TokenCoefficientService
from server import app

RAW_UPSTREAM_KEY = "upstream-secret-key"


class _StubProvider:
    """Minimal provider that yields single data: lines (matching real provider
    behavior). Each chunk is a single line starting with `data:` so that
    ``_extract_usage_from_sse_line`` can parse usage, and
    ``_apply_coefficient_to_sse_event`` can rewrite it.
    """

    name = "stub"

    async def stream_response(self, body, *, request_id=None, thinking_enabled=False):
        yield (
            'data: {"type":"message_start","message":{"id":"msg_x",'
            '"usage":{"input_tokens":100,'
            '"cache_read_input_tokens":80,'
            '"cache_creation_input_tokens":20,'
            '"output_tokens":0}}}\n'
        )
        yield 'data: {"type":"message_delta","usage":{"output_tokens":7}}\n'
        yield 'data: {"type":"message_stop"}\n'


class _StubProviderRegistry:
    def __init__(self, provider):
        self._provider = provider

    def get(self, *_args, **_kwargs):
        return self._provider

    async def cleanup(self):
        pass


@pytest.fixture(autouse=True)
async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    # Seed minimal data for the proxy to resolve a model
    async with session_factory() as session:
        u = User(id=1, email="u@example.com", password_hash="x",
                 balance=10000, role="user", status="active")
        m = Model(id=1, public_name="m1",
                  input_price=15000, output_price=75000, status="active")
        p = Provider(id=1, name="p1", channel_name="ch1",
                     api_base_url="https://x", auth_header="Authorization",
                     adapter="anthropic-messages", status="active", multiplier=1.0)
        route = ModelProviderRoute(model_id=1, provider_id=1,
                                   provider_model="m1", is_default=True,
                                   status="active")
        apikey = ApiKey(id=1, user_id=1, name="k1", key_hash="hash",
                        key_prefix="sk-aaaa", channel_id=None, status="active")
        pk = ProviderKey(
            id=1,
            provider_id=1,
            key_encrypted=encrypt_api_key(RAW_UPSTREAM_KEY, provider_id=1),
            key_prefix="upst****key",
            status="active",
        )
        session.add_all([u, m, p, route, apikey, pk])
        await session.commit()

    # Service: starts with global 0.5
    async with session_factory() as session:
        session.add(TokenCoefficientConfig(scope_type="global", coefficient=0.5))
        await session.commit()

    app.state.token_coefficient_service = TokenCoefficientService(session_factory)
    await app.state.token_coefficient_service.load()

    # Stub provider registry
    app.state.provider_registry = _StubProviderRegistry(_StubProvider())

    # Auth override: return the seeded user/key
    from api.dependencies import require_api_key

    async def _override_require_api_key():
        async with session_factory() as session:
            u = await session.get(User, 1)
            k = await session.get(ApiKey, 1)
            return u, k

    app.dependency_overrides[require_api_key] = _override_require_api_key

    yield session_factory

    app.dependency_overrides.clear()
    await engine.dispose()
    del app.state.token_coefficient_service


@pytest.mark.asyncio
async def test_response_usage_is_adjusted():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-aaaa-whatever"},
            json={
                "model": "m1",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200
    body = r.text

    # message_start usage: input 100*0.5=50, cache_read 80*0.5=40, cache_creation 20*0.5=10
    assert '"input_tokens":50' in body
    assert '"cache_read_input_tokens":40' in body
    assert '"cache_creation_input_tokens":10' in body
    # message_delta: output 7*0.5=3.5 -> ceil=4
    assert '"output_tokens":4' in body


@pytest.mark.asyncio
async def test_pending_billing_stores_adjusted_values(setup_db):
    session_factory = setup_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-aaaa-whatever"},
            json={
                "model": "m1",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200

    # The billing_stream's finally block writes PendingBilling — read it back
    async with session_factory() as session:
        result = await session.execute(select(PendingBilling))
        pb = result.scalar_one_or_none()
        assert pb is not None, "expected a pending_billing row to be written"
        assert pb.input_tokens == 50
        assert pb.cache_read_tokens == 40
        assert pb.cache_creation_tokens == 10
        assert pb.output_tokens == 4

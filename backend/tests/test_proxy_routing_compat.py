"""Compatibility tests for DB-backed proxy routing."""

import os
import sys
from collections.abc import AsyncIterator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request
from starlette.responses import StreamingResponse

from api.models.anthropic import MessagesRequest
from app.database import Base
from app.exceptions import AppException
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider, ProviderKey
from app.models.user import User
from app.routers.proxy import _get_active_upstream_key
from app.routers.proxy import create_message as proxy_create_message
from app.services.api_key_service import hash_key
from app.services.provider_service import encrypt_api_key
from providers.exceptions import UpstreamResponseError
from server import app

RAW_CLIENT_KEY = "sk-" + "b" * 40
RAW_UPSTREAM_KEY = "upstream-secret"


class FakeProvider:
    def __init__(self):
        self.seen_model: str | None = None

    async def stream_response(self, body, request_id: str) -> AsyncIterator[str]:
        self.seen_model = body.model
        yield 'event: message_start\ndata: {"type":"message_start"}\n\n'


class ErrorProvider:
    def __init__(
        self,
        status_code: int,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.calls = 0

    async def stream_response(self, body, request_id: str) -> AsyncIterator[str]:
        self.calls += 1
        raise UpstreamResponseError(
            status_code=self.status_code,
            body=self.body,
            headers=self.headers,
        )
        if False:
            yield ""


class TransportFailureProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def stream_response(self, body, request_id: str) -> AsyncIterator[str]:
        raise self.error
        if False:
            yield ""


class SseErrorProvider:
    async def stream_response(self, body, request_id: str) -> AsyncIterator[str]:
        yield "event: error\n"
        yield (
            'data: {"type":"error","error":{"type":"overloaded_error",'
            '"message":"deepseek/deepseekV4-pro busy"}}\n'
        )
        yield "\n"


class FakeRegistry:
    def __init__(self, provider: FakeProvider):
        self.provider = provider
        self.seen_provider_id: str | None = None
        self.seen_api_key: str | None = None
        self.seen_base_url: str | None = None

    def get(self, provider_id: str, *, api_key: str, base_url: str | None = None):
        self.seen_provider_id = provider_id
        self.seen_api_key = api_key
        self.seen_base_url = base_url
        return self.provider


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
            email="proxy@example.com",
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
                name="client",
                key_prefix=RAW_CLIENT_KEY[:10],
                key_hash=hash_key(RAW_CLIENT_KEY),
                status="active",
            )
        )

        model = Model(
            public_name="claude-opus-4-8",
            description="test",
            input_price=15000,
            output_price=75000,
            status="active",
        )
        provider = Provider(
            name="DeepSeek",
            channel_name="default",
            multiplier=1.0,
            api_base_url="https://api.deepseek.com/anthropic",
            status="active",
        )
        db.add_all([model, provider])
        await db.flush()

        channel = ModelProviderRoute(
            model_id=model.id,
            provider_id=provider.id,
            provider_model="deepseek/deepseekV4-pro",
            is_default=True,
        )
        db.add(channel)
        db.add(
            ProviderKey(
                provider_id=provider.id,
                key_encrypted=encrypt_api_key(RAW_UPSTREAM_KEY, provider_id=provider.id),
                key_prefix="upst****cret",
                status="active",
            )
        )
        await db.commit()

    yield

    await engine.dispose()
    del app.state.db_session_factory
    del app.state.db_engine
    if hasattr(app.state, "provider_registry"):
        del app.state.provider_registry


@pytest.mark.asyncio
async def test_proxy_routes_db_channel_to_provider_registry():
    fake_provider = FakeProvider()
    fake_registry = FakeRegistry(fake_provider)
    app.state.provider_registry = fake_registry

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "只回复 OK"}],
            },
        )

    assert resp.status_code == 200
    assert fake_registry.seen_provider_id == "deepseek"
    assert fake_registry.seen_api_key == RAW_UPSTREAM_KEY
    assert fake_registry.seen_base_url == "https://api.deepseek.com/anthropic"
    assert fake_provider.seen_model == "deepseek/deepseekV4-pro"


@pytest.mark.asyncio
async def test_proxy_canonicalizes_minimax_provider_name():
    fake_provider = FakeProvider()
    fake_registry = FakeRegistry(fake_provider)
    app.state.provider_registry = fake_registry

    async with app.state.db_session_factory() as db:
        provider = (await db.execute(select(Provider))).scalars().first()
        provider.name = "miniMax"
        provider.api_base_url = "https://api.minimaxi.com/anthropic"
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert resp.status_code == 200
    assert fake_registry.seen_provider_id == "minimax"
    assert fake_registry.seen_base_url == "https://api.minimaxi.com/anthropic"


@pytest.mark.asyncio
async def test_proxy_routes_channel_bound_api_key():
    fake_provider = FakeProvider()
    fake_registry = FakeRegistry(fake_provider)
    app.state.provider_registry = fake_registry

    async with app.state.db_session_factory() as db:
        provider = (await db.execute(select(Provider))).scalars().first()
        api_key = (await db.execute(select(ApiKey))).scalars().first()
        api_key.channel_id = provider.id
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert resp.status_code == 200
    assert fake_registry.seen_provider_id == "deepseek"
    assert fake_provider.seen_model == "deepseek/deepseekV4-pro"


@pytest.mark.asyncio
async def test_proxy_reports_config_error_when_provider_key_cannot_be_decrypted():
    async with app.state.db_session_factory() as db:
        provider = (await db.execute(select(Provider))).scalars().first()
        key = (await db.execute(select(ProviderKey))).scalars().first()
        key.key_encrypted = encrypt_api_key(RAW_UPSTREAM_KEY, provider_id=provider.id + 1000)
        await db.commit()

        with pytest.raises(AppException) as exc:
            await _get_active_upstream_key(db, provider.id, channel_id=provider.id)

    assert exc.value.status_code == 500
    assert exc.value.code == "UPSTREAM_CONFIG_ERROR"


@pytest.mark.asyncio
async def test_proxy_releases_request_db_transaction_before_streaming():
    fake_provider = FakeProvider()
    fake_registry = FakeRegistry(fake_provider)

    async with app.state.db_session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == "proxy@example.com"))
        ).scalar_one()
        api_key = (
            await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))
        ).scalar_one()

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/messages",
                "headers": [],
                "app": app,
            }
        )
        body = MessagesRequest(
            model="claude-opus-4-8",
            max_tokens=16,
            messages=[{"role": "user", "content": "只回复 OK"}],
        )

        response = await proxy_create_message(
            request,
            body,
            auth=(user, api_key),
            db=db,
            registry=fake_registry,
        )

        assert isinstance(response, StreamingResponse)
        assert not db.in_transaction()


@pytest.mark.asyncio
async def test_proxy_passes_upstream_error_status_body_and_safe_headers_through():
    upstream_body = (
        b'{"type":"error","error":{"type":"overloaded_error","message":"busy"}}\n'
    )
    fake_provider = ErrorProvider(
        529,
        upstream_body,
        {
            "Content-Type": "application/json",
            "Retry-After": "7",
            "Request-Id": "req_upstream_123",
            "Set-Cookie": "provider-secret=1",
            "Connection": "close",
        },
    )
    app.state.provider_registry = FakeRegistry(fake_provider)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert response.status_code == 529
    assert response.content == upstream_body
    assert response.headers["content-type"] == "application/json"
    assert response.headers["retry-after"] == "7"
    assert response.headers["request-id"] == "req_upstream_123"
    assert "set-cookie" not in response.headers
    assert response.headers.get("connection") != "close"
    assert fake_provider.calls == 1

    async with app.state.db_session_factory() as db:
        assert (await db.execute(select(PendingBilling))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_proxy_hides_upstream_authentication_error():
    fake_provider = ErrorProvider(
        401,
        b'{"error":{"message":"secret upstream API key expired"}}',
        {"Content-Type": "application/json"},
    )
    app.state.provider_registry = FakeRegistry(fake_provider)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "api_error"
    assert "secret upstream API key" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (
            httpx.ReadTimeout(
                "upstream response headers timed out",
                request=httpx.Request("POST", "https://upstream.test/messages"),
            ),
            504,
        ),
        (
            httpx.ConnectError(
                "upstream connection failed",
                request=httpx.Request("POST", "https://upstream.test/messages"),
            ),
            502,
        ),
    ],
)
async def test_proxy_maps_pre_response_transport_failures(error, expected_status):
    app.state.provider_registry = FakeRegistry(TransportFailureProvider(error))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert response.status_code == expected_status
    assert response.json()["error"]["type"] == "api_error"


@pytest.mark.asyncio
async def test_proxy_forwards_sse_error_without_rewriting_or_billing():
    app.state.provider_registry = FakeRegistry(SseErrorProvider())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert response.status_code == 200
    assert response.text == (
        "event: error\n"
        'data: {"type":"error","error":{"type":"overloaded_error",'
        '"message":"deepseek/deepseekV4-pro busy"}}\n\n'
    )
    async with app.state.db_session_factory() as db:
        assert (await db.execute(select(PendingBilling))).scalar_one_or_none() is None

"""Tests for UpdateKeyRequest schema + update_api_key service."""

import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base  # noqa: E402
from app.models.api_key import ApiKey  # noqa: E402
from app.models.provider import Provider  # noqa: E402
from app.models.user import User  # noqa: E402


def test_update_key_request_accepts_channel_id():
    from app.schemas.api_key import UpdateKeyRequest

    obj = UpdateKeyRequest.model_validate({"channelId": 7})
    assert obj.channel_id == 7


def test_update_key_request_accepts_null_channel_id():
    from app.schemas.api_key import UpdateKeyRequest

    obj = UpdateKeyRequest.model_validate({"channelId": None})
    assert obj.channel_id is None


def test_update_key_request_requires_channel_id_field():
    from pydantic import ValidationError

    from app.schemas.api_key import UpdateKeyRequest

    try:
        UpdateKeyRequest.model_validate({})
    except ValidationError:
        return
    raise AssertionError("expected ValidationError when channelId missing")


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(
                    id=1,
                    email="t@e.com",
                    password_hash="x",
                    balance=10000,
                    role="user",
                    status="active",
                ),
                User(
                    id=2,
                    email="o@e.com",
                    password_hash="x",
                    balance=10000,
                    role="user",
                    status="active",
                ),
                Provider(
                    id=10,
                    name="p1",
                    channel_name="线路A",
                    api_base_url="http://x",
                    auth_header="Authorization",
                    adapter="openai-chat-completions",
                    multiplier=1.0,
                    status="active",
                ),
                Provider(
                    id=11,
                    name="p2",
                    channel_name="线路B",
                    api_base_url="http://x",
                    auth_header="Authorization",
                    adapter="openai-chat-completions",
                    multiplier=1.5,
                    status="active",
                ),
                Provider(
                    id=12,
                    name="p3",
                    channel_name="线路C",
                    api_base_url="http://x",
                    auth_header="Authorization",
                    adapter="openai-chat-completions",
                    multiplier=2.0,
                    status="inactive",
                ),
                ApiKey(
                    id=100,
                    user_id=1,
                    name="k1",
                    key_prefix="sk-aaa",
                    key_hash="h",
                    status="active",
                    channel_id=10,
                ),
                ApiKey(
                    id=101,
                    user_id=1,
                    name="k2",
                    key_prefix="sk-bbb",
                    key_hash="h",
                    status="revoked",
                    channel_id=10,
                ),
            ]
        )
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_update_key_switch_channel(session_factory):
    from app.services.api_key_service import update_api_key

    async with session_factory() as session:
        user = await session.get(User, 1)
        key = await update_api_key(session, user=user, key_id=100, channel_id=11)
        assert key.channel_id == 11
        assert key.status == "active"


@pytest.mark.asyncio
async def test_update_key_clear_channel(session_factory):
    from app.services.api_key_service import update_api_key

    async with session_factory() as session:
        user = await session.get(User, 1)
        key = await update_api_key(session, user=user, key_id=100, channel_id=None)
        assert key.channel_id is None


@pytest.mark.asyncio
async def test_update_key_channel_unavailable(session_factory):
    from app.exceptions import AppException
    from app.services.api_key_service import update_api_key

    async with session_factory() as session:
        user = await session.get(User, 1)
        with pytest.raises(AppException) as exc:
            await update_api_key(session, user=user, key_id=100, channel_id=12)
        assert exc.value.status_code == 400
        assert exc.value.code == "CHANNEL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_update_key_not_found(session_factory):
    from app.exceptions import AppException
    from app.services.api_key_service import update_api_key

    async with session_factory() as session:
        user = await session.get(User, 1)
        # id=101 属于同一用户但已 revoked → 400；这里测不存在/越权用 id=999
        with pytest.raises(AppException) as exc:
            await update_api_key(session, user=user, key_id=999, channel_id=11)
        assert exc.value.status_code == 404
        assert exc.value.code == "KEY_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_key_revoked(session_factory):
    from app.exceptions import AppException
    from app.services.api_key_service import update_api_key

    async with session_factory() as session:
        user = await session.get(User, 1)
        with pytest.raises(AppException) as exc:
            await update_api_key(session, user=user, key_id=101, channel_id=11)
        assert exc.value.status_code == 400
        assert exc.value.code == "KEY_ALREADY_REVOKED"

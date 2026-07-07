"""Tests for UpdateKeyRequest schema + update_api_key service."""

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


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

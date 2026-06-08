"""Tests for CreateKeyRequest + KeyResponse schema updates."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_create_key_request_requires_channel_id():
    from pydantic import ValidationError

    from app.schemas.api_key import CreateKeyRequest

    try:
        CreateKeyRequest.model_validate({"name": "x"})
    except ValidationError:
        return
    raise AssertionError("expected ValidationError when channelId missing")


def test_create_key_request_accepts_channel_id_alias():
    from app.schemas.api_key import CreateKeyRequest

    obj = CreateKeyRequest.model_validate({"name": "x", "channelId": 7})
    assert obj.channel_id == 7


def test_create_key_request_rejects_zero_channel_id():
    from pydantic import ValidationError

    from app.schemas.api_key import CreateKeyRequest

    try:
        CreateKeyRequest.model_validate({"name": "x", "channelId": 0})
    except ValidationError:
        return
    raise AssertionError("expected ValidationError when channelId <= 0")


def test_key_response_channel_id_optional():
    from app.schemas.api_key import KeyResponse

    legacy = KeyResponse.model_validate(
        {
            "id": 1,
            "name": "x",
            "keyPrefix": "sk-abc",
            "status": "active",
            "createdAt": "2026-06-01T00:00:00Z",
            "lastUsedAt": None,
        }
    )
    assert legacy.channel_id is None
    assert legacy.channel_name is None


def test_key_response_with_channel_id():
    from app.schemas.api_key import KeyResponse

    bound = KeyResponse.model_validate(
        {
            "id": 2,
            "name": "k2",
            "keyPrefix": "sk-def",
            "status": "active",
            "createdAt": "2026-06-01T00:00:00Z",
            "lastUsedAt": None,
            "channelId": 7,
            "channelName": "awsq",
        }
    )
    assert bound.channel_id == 7
    assert bound.channel_name == "awsq"

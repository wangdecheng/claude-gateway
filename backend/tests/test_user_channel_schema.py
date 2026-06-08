"""User-side channel schemas must never expose provider.name."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_user_channel_info_excludes_name():
    from app.schemas.channel import UserChannelInfo

    obj = UserChannelInfo.model_validate(
        {"id": 1, "channelName": "awsq", "multiplier": 0.3, "isDefault": True}
    )
    dumped = obj.model_dump(by_alias=True)
    assert "name" not in dumped
    assert dumped["channelName"] == "awsq"
    assert dumped["multiplier"] == 0.3
    assert dumped["isDefault"] is True


def test_user_channel_info_ignores_extra_name_field():
    from app.schemas.channel import UserChannelInfo

    obj = UserChannelInfo.model_validate(
        {
            "id": 1,
            "name": "Anthropic",
            "channelName": "awsq",
            "multiplier": 0.3,
            "isDefault": True,
        }
    )
    assert not hasattr(obj, "name")
    dumped = obj.model_dump(by_alias=True)
    assert "name" not in dumped


def test_channel_model_row_aliases():
    from app.schemas.channel import ChannelModelRow

    obj = ChannelModelRow.model_validate(
        {
            "id": 5,
            "publicName": "claude-haiku-4-5",
            "description": None,
            "inputPrice": 0.3,
            "outputPrice": 1.5,
            "inputBasePrice": 1.0,
            "outputBasePrice": 5.0,
        }
    )
    assert obj.public_name == "claude-haiku-4-5"
    assert obj.input_price == 0.3


def test_user_channel_with_models_dump_aliases():
    from app.schemas.channel import (
        ChannelModelRow,
        UserChannelInfo,
        UserChannelWithModels,
    )

    obj = UserChannelWithModels(
        channel=UserChannelInfo.model_validate(
            {"id": 1, "channelName": "awsq", "multiplier": 0.3, "isDefault": True}
        ),
        models=[
            ChannelModelRow.model_validate(
                {
                    "id": 5,
                    "publicName": "haiku",
                    "description": None,
                    "inputPrice": 0.3,
                    "outputPrice": 1.5,
                    "inputBasePrice": 1.0,
                    "outputBasePrice": 5.0,
                }
            )
        ],
    )
    dumped = obj.model_dump(by_alias=True)
    assert "channel" in dumped
    assert "name" not in dumped["channel"]
    assert dumped["channel"]["channelName"] == "awsq"


def test_model_channel_info_excludes_provider_name():
    from app.schemas.model import ChannelInfo

    obj = ChannelInfo.model_validate(
        {"id": 1, "channelName": "awsq", "multiplier": 0.3, "isDefault": False}
    )
    dumped = obj.model_dump(by_alias=True)
    assert "providerName" not in dumped
    assert "name" not in dumped
    assert dumped["channelName"] == "awsq"

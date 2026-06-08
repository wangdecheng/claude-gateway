"""Tests for Provider model — channel display fields."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_provider_has_channel_name_column():
    from app.models.provider import Provider

    assert "channel_name" in Provider.__table__.columns


def test_provider_has_multiplier_column_with_default():
    from app.models.provider import Provider

    col = Provider.__table__.columns["multiplier"]
    assert col.default is not None
    assert col.default.arg == 1.0


def test_provider_channel_name_not_nullable():
    from app.models.provider import Provider

    col = Provider.__table__.columns["channel_name"]
    assert col.nullable is False

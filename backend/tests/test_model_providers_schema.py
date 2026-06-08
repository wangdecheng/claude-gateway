"""Tests for ModelProviderRoute model."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_model_provider_route_table_name():
    from app.models.model_provider_route import ModelProviderRoute

    assert ModelProviderRoute.__tablename__ == "model_providers"


def test_model_provider_route_columns():
    from app.models.model_provider_route import ModelProviderRoute

    cols = {c.name for c in ModelProviderRoute.__table__.columns}
    assert {"id", "model_id", "provider_id", "provider_model", "is_default", "created_at"} <= cols


def test_model_provider_route_unique_constraint():
    from app.models.model_provider_route import ModelProviderRoute

    constraints = {c.name for c in ModelProviderRoute.__table__.constraints}
    assert "uq_model_provider" in constraints


def test_channel_key_provider_id_fk():
    from app.models.channel_key import ChannelKey

    cols = {c.name for c in ChannelKey.__table__.columns}
    assert "channel_id" not in cols
    assert "provider_id" in cols


def test_channel_key_provider_id_targets_providers():
    from app.models.channel_key import ChannelKey

    col = ChannelKey.__table__.columns["provider_id"]
    fk_targets = {fk.column.table.name for fk in col.foreign_keys}
    assert "providers" in fk_targets

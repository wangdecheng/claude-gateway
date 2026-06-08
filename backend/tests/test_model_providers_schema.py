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

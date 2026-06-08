"""Tests for ApiKey model — channel_id FK."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_api_key_has_optional_channel_id():
    from app.models.api_key import ApiKey

    col = ApiKey.__table__.columns["channel_id"]
    assert col.nullable is True
    # Should FK to providers.id
    fk_targets = {fk.column.table.name for fk in col.foreign_keys}
    assert "providers" in fk_targets

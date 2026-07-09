import hashlib
from types import SimpleNamespace

from app.services import provider_service


def test_aes_key_uses_settings_encryption_key_when_process_env_is_unset(monkeypatch):
    monkeypatch.delenv("UPSTREAM_KEY_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(provider_service, "_ENCRYPTION_KEY", None)
    monkeypatch.setattr(
        provider_service,
        "settings",
        SimpleNamespace(debug=True, upstream_key_encryption_key="server-secret"),
    )

    assert provider_service._get_aes_key() == hashlib.sha256(b"server-secret").digest()

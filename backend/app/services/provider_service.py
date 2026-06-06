"""Provider, ProviderKey and ChannelConfig management service.

Handles:
  - Provider CRUD (list, create, update, toggle status)
  - ProviderKey CRUD (list masked, add, revoke)
  - ChannelConfig CRUD for channel multiplier/default management
  - AES-256-GCM encryption / decryption of upstream API keys
  - Key pool round-robin selection for proxy use
"""

import base64
import hashlib
import logging
import os
import random
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import AppException
from app.models.channel_key import ChannelKey
from app.models.model import ChannelConfig, Model
from app.models.provider import Provider, ProviderKey
from app.models.request_log import RequestLog
from app.schemas.admin_provider import (
    ProviderCreate,
    ProviderUpdate,
)

logger = logging.getLogger("high-api.provider_service")

# ── Encryption helpers ───────────────────────────────────────────────

_ENCRYPTION_KEY: bytes | None = None


def _get_aes_key() -> bytes:
    """Derive a 32-byte AES key from UPSTREAM_KEY_ENCRYPTION_KEY env var."""
    global _ENCRYPTION_KEY
    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY
    raw = os.environ.get("UPSTREAM_KEY_ENCRYPTION_KEY", "")
    if not raw:
        if not settings.debug:
            logger.critical(
                "UPSTREAM_KEY_ENCRYPTION_KEY not set in non-debug mode — refusing to start"
            )
            sys.exit(1)
        # Debug mode: use dev default
        raw = "dev-encryption-key-change-in-production"
        logger.warning("UPSTREAM_KEY_ENCRYPTION_KEY not set — using INSECURE dev default")
    _ENCRYPTION_KEY = hashlib.sha256(raw.encode()).digest()
    return _ENCRYPTION_KEY


def encrypt_api_key(plaintext: str, provider_id: int | None = None) -> str:
    """AES-256-GCM encrypt an upstream API key.

    Returns a base64-encoded string: nonce (12 bytes) + ciphertext.

    If provider_id is provided, it is bound as associated data to prevent
    cross-provider key substitution.
    """
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    aad = _provider_id_aad(provider_id) if provider_id is not None else None
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), aad)
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode()


def decrypt_api_key(encrypted: str, provider_id: int | None = None) -> str:
    """AES-256-GCM decrypt an upstream API key.

    If provider_id is provided, it must match the value used during encryption
    (authenticated associated data check).
    """
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    combined = base64.b64decode(encrypted)
    nonce, ciphertext = combined[:12], combined[12:]
    aad = _provider_id_aad(provider_id) if provider_id is not None else None
    return aesgcm.decrypt(nonce, ciphertext, aad).decode()


def _provider_id_aad(provider_id: int) -> bytes:
    """Encode provider_id as associated data for AES-GCM authentication."""
    return f"provider:{provider_id}".encode()


def _make_key_prefix(plaintext: str) -> str:
    """Build a display prefix: first 4 + '****' + last 4 chars."""
    if len(plaintext) <= 8:
        return plaintext[:4] + "****"
    return plaintext[:4] + "****" + plaintext[-4:]


# Maximum length of the display prefix (first 4 + "****" + last 4 = 12 chars)
_KEY_PREFIX_MAX_LEN = 12


# ── Provider CRUD ────────────────────────────────────────────────────


async def list_providers(db: AsyncSession) -> list[dict]:
    """Return all providers with key counts."""
    result = await db.execute(
        select(
            Provider,
            func.count(ProviderKey.id).label("key_count"),
            func.count(ProviderKey.id)
            .filter(ProviderKey.status == "active")
            .label("active_key_count"),
        )
        .where(Provider.status != "deleted")
        .outerjoin(ProviderKey, ProviderKey.provider_id == Provider.id)
        .group_by(Provider.id)
        .order_by(Provider.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "id": row.Provider.id,
            "name": row.Provider.name,
            "api_base_url": row.Provider.api_base_url,
            "auth_header": row.Provider.auth_header,
            "adapter": row.Provider.adapter,
            "key_count": row.key_count,
            "active_key_count": row.active_key_count,
            "status": row.Provider.status,
            "created_at": row.Provider.created_at.isoformat(),
        }
        for row in rows
    ]


async def create_provider(db: AsyncSession, data: ProviderCreate) -> Provider:
    """Create a provider and optionally its initial key pool."""
    # Check name uniqueness
    existing = await db.execute(select(Provider).where(Provider.name == data.name))
    if existing.scalar_one_or_none():
        raise AppException(
            status_code=409,
            error="供应商名称已存在",
            code="PROVIDER_NAME_EXISTS",
        )

    provider = Provider(
        name=data.name,
        api_base_url=data.api_base_url,
        auth_header=data.auth_header,
        adapter=data.adapter,
    )
    db.add(provider)
    await db.flush()  # Get provider.id

    # Encrypt and insert initial keys
    if data.keys:
        for plaintext in data.keys:
            stripped = plaintext.strip()
            if not stripped:
                continue
            encrypted = encrypt_api_key(stripped, provider_id=provider.id)
            prefix = _make_key_prefix(stripped)
            db.add(
                ProviderKey(
                    provider_id=provider.id,
                    key_encrypted=encrypted,
                    key_prefix=prefix,
                )
            )
        await db.flush()

    logger.info("Provider '%s' created (id=%d)", provider.name, provider.id)
    return provider


async def update_provider(db: AsyncSession, provider_id: int, data: ProviderUpdate) -> Provider:
    """Update editable fields of a provider."""
    provider = await _get_provider_or_404(db, provider_id)

    update_data = data.model_dump(exclude_unset=True, by_alias=False)

    # Check name uniqueness if renaming
    new_name = update_data.get("name")
    if new_name is not None and new_name != provider.name:
        existing = await db.execute(
            select(Provider).where(
                Provider.name == new_name,
                Provider.id != provider_id,
            )
        )
        if existing.scalar_one_or_none():
            raise AppException(
                status_code=409,
                error="供应商名称已存在",
                code="PROVIDER_NAME_EXISTS",
            )

    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.flush()
    logger.info("Provider id=%d updated (fields: %s)", provider_id, list(update_data.keys()))
    return provider


async def toggle_provider_status(db: AsyncSession, provider_id: int) -> Provider:
    """Toggle provider status between active and inactive."""
    provider = await _get_provider_or_404(db, provider_id)
    provider.status = "inactive" if provider.status == "active" else "active"
    await db.flush()
    logger.info(
        "Provider '%s' (id=%d) status → %s",
        provider.name,
        provider.id,
        provider.status,
    )
    return provider


async def _get_provider_or_404(db: AsyncSession, provider_id: int) -> Provider:
    """Fetch a provider by id or raise 404."""
    result = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise AppException(
            status_code=404,
            error="供应商不存在",
            code="PROVIDER_NOT_FOUND",
        )
    return provider


# ── ProviderKey management ────────────────────────────────────────────


async def get_provider_keys(
    db: AsyncSession,
    provider_id: int,
) -> list[ProviderKey]:
    """Return all keys for a provider (masked — never return plaintext)."""
    # Ensure provider exists
    await _get_provider_or_404(db, provider_id)
    result = await db.execute(
        select(ProviderKey)
        .where(ProviderKey.provider_id == provider_id)
        .order_by(ProviderKey.created_at.desc())
    )
    return list(result.scalars().all())


async def add_provider_keys(
    db: AsyncSession,
    provider_id: int,
    keys: list[str],
) -> list[str]:
    """Encrypt and insert new keys for a provider. Returns masked prefixes."""
    await _get_provider_or_404(db, provider_id)

    prefixes: list[str] = []
    for plaintext in keys:
        stripped = plaintext.strip()
        if not stripped:
            continue
        encrypted = encrypt_api_key(stripped, provider_id=provider_id)
        prefix = _make_key_prefix(stripped)
        db.add(
            ProviderKey(
                provider_id=provider_id,
                key_encrypted=encrypted,
                key_prefix=prefix,
            )
        )
        prefixes.append(prefix)

    await db.flush()
    logger.info(
        "Added %d key(s) to provider id=%d",
        len(prefixes),
        provider_id,
    )
    return prefixes


async def revoke_provider_key(db: AsyncSession, key_id: int) -> ProviderKey:
    """Soft-delete (revoke) a single provider key."""
    result = await db.execute(select(ProviderKey).where(ProviderKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise AppException(
            status_code=404,
            error="Key 不存在",
            code="PROVIDER_KEY_NOT_FOUND",
        )
    if key.status == "revoked":
        raise AppException(
            status_code=400,
            error="该 Key 已被移除",
            code="PROVIDER_KEY_ALREADY_REVOKED",
        )

    key.status = "revoked"
    await db.flush()
    logger.info("ProviderKey id=%d revoked", key_id)
    return key


# ── Key pool for proxy use ────────────────────────────────────────────


async def get_active_upstream_key(
    db: AsyncSession,
    provider_id: int,
) -> str | None:
    """Return one decrypted active key from the provider's key pool.

    Selects randomly from the active key pool for basic load distribution.
    Returns None when no active key is available.
    """
    result = await db.execute(
        select(ProviderKey)
        .where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.status == "active",
        )
        .order_by(ProviderKey.id)
    )
    keys = result.scalars().all()
    if not keys:
        return None
    selected = random.choice(keys)
    return decrypt_api_key(selected.key_encrypted, provider_id=provider_id)


# ── ChannelConfig management (Story 4.3) ─────────────────────────────


def _format_channel_row(channel: ChannelConfig, model: Model, provider: Provider) -> dict:
    """Format a ChannelConfig joined with model/provider for admin responses."""
    return {
        "id": channel.id,
        "model_id": channel.model_id,
        "model_name": model.public_name,
        "model_status": model.status,
        "provider_id": channel.provider_id,
        "provider_name": provider.name,
        "provider_status": provider.status,
        "provider_model_id": channel.provider_model_id,
        "multiplier": channel.multiplier,
        "is_default": channel.is_default,
        "status": channel.status,
        "created_at": channel.created_at.isoformat(),
    }


async def list_channel_configs(db: AsyncSession) -> list[dict]:
    """Return all channel configs with model/provider display fields."""
    result = await db.execute(
        select(ChannelConfig, Model, Provider)
        .join(Model, ChannelConfig.model_id == Model.id)
        .join(Provider, ChannelConfig.provider_id == Provider.id)
        .where(ChannelConfig.status != "deleted")
        .order_by(Model.public_name.asc(), ChannelConfig.multiplier.asc())
    )
    return [_format_channel_row(ch, model, provider) for ch, model, provider in result.all()]


async def _get_channel_with_context_or_404(
    db: AsyncSession,
    channel_id: int,
) -> tuple[ChannelConfig, Model, Provider]:
    result = await db.execute(
        select(ChannelConfig, Model, Provider)
        .join(Model, ChannelConfig.model_id == Model.id)
        .join(Provider, ChannelConfig.provider_id == Provider.id)
        .where(ChannelConfig.id == channel_id)
    )
    row = result.one_or_none()
    if not row:
        raise AppException(
            status_code=404,
            error="渠道配置不存在",
            code="CHANNEL_NOT_FOUND",
        )
    return row


async def _get_model_or_404(db: AsyncSession, model_id: int) -> Model:
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")
    return model


async def _ensure_single_default(db: AsyncSession, model_id: int, channel: ChannelConfig) -> None:
    """Make the given channel the only default channel for its model.

    Uses SELECT ... FOR UPDATE to serialize concurrent default changes.
    A DB-level partial unique index on (model_id) WHERE is_default = TRUE
    is recommended for complete protection across transactions.
    """
    # Lock all channels for this model to prevent concurrent default changes
    await db.execute(
        select(ChannelConfig).where(ChannelConfig.model_id == model_id).with_for_update()
    )
    await db.execute(
        update(ChannelConfig).where(ChannelConfig.model_id == model_id).values(is_default=False)
    )
    channel.is_default = True


async def create_channel_config(
    db: AsyncSession,
    *,
    model_id: int,
    provider_id: int,
    provider_model_id: str,
    multiplier: float,
    is_default: bool = False,
) -> dict:
    """Create a model-provider channel config."""
    # 1. Validate multiplier first (cheap, no DB)
    if multiplier <= 0:
        raise AppException(
            status_code=400,
            error="倍率必须大于 0",
            code="INVALID_MULTIPLIER",
        )

    # 2. Check model and provider exist
    model = await _get_model_or_404(db, model_id)
    provider = await _get_provider_or_404(db, provider_id)

    # 3. Check for duplicate active channel (with lock to prevent race)
    existing = await db.execute(
        select(ChannelConfig)
        .where(
            ChannelConfig.model_id == model_id,
            ChannelConfig.provider_id == provider_id,
            ChannelConfig.status == "active",
        )
        .with_for_update()
    )
    if existing.scalar_one_or_none():
        raise AppException(
            status_code=409,
            error="该供应商-模型渠道已存在",
            code="CHANNEL_ALREADY_EXISTS",
        )

    channel = ChannelConfig(
        model_id=model_id,
        provider_id=provider_id,
        provider_model_id=provider_model_id,
        multiplier=multiplier,
        is_default=False,
        status="active",
    )
    db.add(channel)
    await db.flush()

    if is_default:
        await _ensure_single_default(db, model_id, channel)
        await db.flush()

    return _format_channel_row(channel, model, provider)


async def update_channel_config(
    db: AsyncSession,
    channel_id: int,
    *,
    provider_model_id: str | None = None,
    multiplier: float | None = None,
    is_default: bool | None = None,
) -> dict:
    """Update provider_model_id / multiplier / default flag for a channel config."""
    channel, model, provider = await _get_channel_with_context_or_404(db, channel_id)

    if provider_model_id is not None:
        channel.provider_model_id = provider_model_id

    if multiplier is not None:
        if multiplier <= 0:
            raise AppException(
                status_code=400,
                error="倍率必须大于 0",
                code="INVALID_MULTIPLIER",
            )
        channel.multiplier = multiplier

    if is_default is True:
        await _ensure_single_default(db, channel.model_id, channel)
    elif is_default is False:
        channel.is_default = False

    await db.flush()
    return _format_channel_row(channel, model, provider)


async def set_channel_multiplier(
    db: AsyncSession,
    channel_id: int,
    multiplier: float,
) -> dict:
    """Compatibility helper for Story 4.3 naming."""
    return await update_channel_config(db, channel_id, multiplier=multiplier)


async def toggle_channel_status(db: AsyncSession, channel_id: int) -> dict:
    """Toggle a channel status between active and inactive."""
    channel, model, provider = await _get_channel_with_context_or_404(db, channel_id)
    if channel.status == "active":
        channel.status = "inactive"
        # Clear default flag so admin view doesn't show a disabled default.
        # Public API already handles this via _normalize_default_channels.
        if channel.is_default:
            channel.is_default = False
    elif channel.status == "inactive":
        channel.status = "active"
    else:
        raise AppException(
            status_code=400,
            error="无效的渠道状态",
            code="INVALID_CHANNEL_STATUS",
        )
    await db.flush()
    return _format_channel_row(channel, model, provider)


async def delete_provider(db: AsyncSession, provider_id: int) -> dict:
    """Delete a provider — hard if no RequestLog references, soft otherwise.

    Blocked if Model, ChannelConfig, or active ProviderKey records reference this provider.
    """
    # 1. Find provider
    provider = await _get_provider_or_404(db, provider_id)
    if provider.status == "deleted":
        raise AppException(
            status_code=404, error="供应商不存在", code="PROVIDER_NOT_FOUND"
        )

    # 2. Check blocking dependents
    blocking: dict[str, int] = {}

    ch_count_result = await db.execute(
        select(func.count(ChannelConfig.id)).where(
            ChannelConfig.provider_id == provider_id
        )
    )
    blocking["channels"] = ch_count_result.scalar_one()

    key_count_result = await db.execute(
        select(func.count(ProviderKey.id)).where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.status == "active",
        )
    )
    blocking["keys"] = key_count_result.scalar_one()

    total_blocking = blocking["channels"] + blocking["keys"]
    if total_blocking > 0:
        parts = []
        if blocking["channels"]:
            parts.append(f"{blocking['channels']} 个渠道配置")
        if blocking["keys"]:
            parts.append(f"{blocking['keys']} 把活跃 Key")
        raise AppException(
            status_code=409,
            error=f"无法删除：供应商下有 {'、'.join(parts)}，请先清理",
            code="HAS_DEPENDENTS",
        )

    # 3. Check RequestLog to decide hard vs soft
    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(
            RequestLog.provider_id == provider_id
        )
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        provider.status = "deleted"
        method = "soft"
    else:
        # Hard delete: cascade-delete all ProviderKeys (revoked + active)
        pk_result = await db.execute(
            select(ProviderKey).where(ProviderKey.provider_id == provider_id)
        )
        for pk in pk_result.scalars().all():
            await db.delete(pk)
        await db.delete(provider)
        method = "hard"

    await db.flush()
    logger.info(
        "Provider id=%d (%s) %s-deleted",
        provider_id,
        provider.name if has_request_logs else "",
        method,
    )
    return {"deleted": True, "method": method, "id": provider_id}


async def delete_channel(db: AsyncSession, channel_id: int) -> dict:
    """Delete a channel config — hard if no RequestLog references, soft otherwise.

    Blocked if ChannelKey records reference this channel.
    """
    # 1. Find channel
    ch_result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise AppException(
            status_code=404, error="渠道配置不存在", code="CHANNEL_NOT_FOUND"
        )
    if channel.status == "deleted":
        raise AppException(
            status_code=404, error="渠道配置不存在", code="CHANNEL_NOT_FOUND"
        )

    # 2. Check blocking dependents: ChannelKey
    ck_count_result = await db.execute(
        select(func.count(ChannelKey.id)).where(
            ChannelKey.channel_id == channel_id
        )
    )
    ck_count = ck_count_result.scalar_one()
    if ck_count > 0:
        raise AppException(
            status_code=409,
            error=f"无法删除：该渠道下有 {ck_count} 个 Key 绑定，请先清理",
            code="HAS_DEPENDENTS",
        )

    # 3. Check RequestLog to decide hard vs soft
    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(
            RequestLog.channel_id == channel_id
        )
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        channel.status = "deleted"
        if channel.is_default:
            channel.is_default = False
        method = "soft"
    else:
        await db.delete(channel)
        method = "hard"

    await db.flush()
    logger.info("Channel id=%d %s-deleted", channel_id, method)
    return {"deleted": True, "method": method, "id": channel_id}

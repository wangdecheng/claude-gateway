"""Provider, ProviderKey and ModelProviderRoute management service.

Handles:
  - Provider CRUD (list, create, update, toggle status)
  - ProviderKey CRUD (list masked, add, revoke)
  - ModelProviderRoute CRUD for (model ↔ provider) routing
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
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
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
            "channel_name": row.Provider.channel_name,
            "multiplier": row.Provider.multiplier,
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
    """Create a provider and optionally its initial key pool.

    Validates (name, channel_name) uniqueness before insert.
    """
    # Check (name, channel_name) uniqueness
    existing = await db.execute(
        select(Provider).where(
            Provider.name == data.name,
            Provider.channel_name == data.channel_name,
        )
    )
    if existing.scalar_one_or_none():
        raise AppException(
            status_code=409,
            error="供应商 (name, channel_name) 组合已存在",
            code="PROVIDER_NAME_EXISTS",
        )

    provider = Provider(
        name=data.name,
        channel_name=data.channel_name,
        multiplier=data.multiplier,
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

    logger.info(
        "Provider '%s/%s' created (id=%d)",
        provider.name,
        provider.channel_name,
        provider.id,
    )
    return provider


async def update_provider(db: AsyncSession, provider_id: int, data: ProviderUpdate) -> Provider:
    """Update editable fields of a provider.

    Editable: channel_name, multiplier, api_base_url, auth_header, adapter.
    Name is not editable (preserves stable identity for SK bindings).
    """
    provider = await _get_provider_or_404(db, provider_id)

    update_data = data.model_dump(exclude_unset=True, by_alias=False)

    # Check (name, channel_name) uniqueness if channel_name changes
    new_channel_name = update_data.get("channel_name")
    if new_channel_name is not None and new_channel_name != provider.channel_name:
        existing = await db.execute(
            select(Provider).where(
                Provider.name == provider.name,
                Provider.channel_name == new_channel_name,
                Provider.id != provider_id,
            )
        )
        if existing.scalar_one_or_none():
            raise AppException(
                status_code=409,
                error="供应商 (name, channel_name) 组合已存在",
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
        "Provider '%s/%s' (id=%d) status → %s",
        provider.name,
        provider.channel_name,
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


# ── ModelProviderRoute management ────────────────────────────────────


def _format_route_row(
    route: ModelProviderRoute, model: Model, provider: Provider
) -> dict:
    """Format a ModelProviderRoute joined with model/provider for admin responses."""
    return {
        "id": route.id,
        "model_id": model.id,
        "model_name": model.public_name,
        "model_status": model.status,
        "provider_id": provider.id,
        "provider_name": provider.name,
        "provider_channel_name": provider.channel_name,
        "provider_multiplier": provider.multiplier,
        "provider_status": provider.status,
        "provider_model": route.provider_model,
        "is_default": route.is_default,
        "status": route.status,
        "created_at": route.created_at.isoformat(),
    }


async def list_model_provider_routes(db: AsyncSession) -> list[dict]:
    """Return all (model, provider) routes with model/provider display fields."""
    result = await db.execute(
        select(ModelProviderRoute, Model, Provider)
        .join(Model, ModelProviderRoute.model_id == Model.id)
        .join(Provider, ModelProviderRoute.provider_id == Provider.id)
        .where(ModelProviderRoute.status != "deleted")
        .order_by(Model.public_name.asc(), Provider.multiplier.asc())
    )
    return [_format_route_row(route, model, provider) for route, model, provider in result.all()]


async def _get_route_with_context_or_404(
    db: AsyncSession,
    route_id: int,
) -> tuple[ModelProviderRoute, Model, Provider]:
    result = await db.execute(
        select(ModelProviderRoute, Model, Provider)
        .join(Model, ModelProviderRoute.model_id == Model.id)
        .join(Provider, ModelProviderRoute.provider_id == Provider.id)
        .where(ModelProviderRoute.id == route_id)
    )
    row = result.one_or_none()
    if not row:
        raise AppException(
            status_code=404,
            error="渠道路由不存在",
            code="ROUTE_NOT_FOUND",
        )
    return row


async def _get_model_or_404(db: AsyncSession, model_id: int) -> Model:
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")
    return model


async def _ensure_single_default_route(
    db: AsyncSession, model_id: int, route: ModelProviderRoute
) -> None:
    """Make the given route the only default for its model.

    Uses SELECT ... FOR UPDATE to serialize concurrent default changes.
    """
    # Lock all routes for this model to prevent concurrent default changes
    await db.execute(
        select(ModelProviderRoute)
        .where(ModelProviderRoute.model_id == model_id)
        .with_for_update()
    )
    await db.execute(
        update(ModelProviderRoute)
        .where(ModelProviderRoute.model_id == model_id)
        .values(is_default=False)
    )
    route.is_default = True


async def create_model_provider_route(
    db: AsyncSession,
    *,
    model_id: int,
    provider_id: int,
    provider_model: str,
    is_default: bool = False,
) -> dict:
    """Create a (model, provider) routing entry."""
    # 1. Validate model and provider exist
    model = await _get_model_or_404(db, model_id)
    provider = await _get_provider_or_404(db, provider_id)

    if provider.status != "active":
        raise AppException(
            status_code=400,
            error="供应商已停用，无法创建路由",
            code="PROVIDER_INACTIVE",
        )

    # 2. Check for duplicate active route (with lock to prevent race)
    existing = await db.execute(
        select(ModelProviderRoute)
        .where(
            ModelProviderRoute.model_id == model_id,
            ModelProviderRoute.provider_id == provider_id,
            ModelProviderRoute.status == "active",
        )
        .with_for_update()
    )
    if existing.scalar_one_or_none():
        raise AppException(
            status_code=409,
            error="该供应商-模型路由已存在",
            code="ROUTE_ALREADY_EXISTS",
        )

    route = ModelProviderRoute(
        model_id=model_id,
        provider_id=provider_id,
        provider_model=provider_model,
        is_default=False,
        status="active",
    )
    db.add(route)
    await db.flush()

    if is_default:
        await _ensure_single_default_route(db, model_id, route)
        await db.flush()

    return _format_route_row(route, model, provider)


async def update_model_provider_route(
    db: AsyncSession,
    route_id: int,
    *,
    provider_model: str | None = None,
    is_default: bool | None = None,
) -> dict:
    """Update provider_model and/or default flag for a route."""
    route, model, provider = await _get_route_with_context_or_404(db, route_id)

    if provider_model is not None:
        route.provider_model = provider_model

    if is_default is True:
        await _ensure_single_default_route(db, route.model_id, route)
    elif is_default is False:
        route.is_default = False

    await db.flush()
    return _format_route_row(route, model, provider)


async def toggle_route_status(db: AsyncSession, route_id: int) -> dict:
    """Toggle a route's status between active and inactive."""
    route, model, provider = await _get_route_with_context_or_404(db, route_id)
    if route.status == "active":
        route.status = "inactive"
        if route.is_default:
            route.is_default = False
    elif route.status == "inactive":
        route.status = "active"
    else:
        raise AppException(
            status_code=400,
            error="无效的路由状态",
            code="INVALID_ROUTE_STATUS",
        )
    await db.flush()
    return _format_route_row(route, model, provider)


async def delete_provider(db: AsyncSession, provider_id: int) -> dict:
    """Delete a provider — hard if no RequestLog references, soft otherwise.

    Blocked if any ModelProviderRoute, ChannelKey, or active ProviderKey
    records reference this provider.
    """
    # 1. Find provider
    provider = await _get_provider_or_404(db, provider_id)
    if provider.status == "deleted":
        raise AppException(
            status_code=404, error="供应商不存在", code="PROVIDER_NOT_FOUND"
        )

    # 2. Check blocking dependents
    blocking: dict[str, int] = {}

    route_count_result = await db.execute(
        select(func.count(ModelProviderRoute.id)).where(
            ModelProviderRoute.provider_id == provider_id,
            ModelProviderRoute.status != "deleted",
        )
    )
    blocking["routes"] = route_count_result.scalar_one()

    key_count_result = await db.execute(
        select(func.count(ProviderKey.id)).where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.status == "active",
        )
    )
    blocking["keys"] = key_count_result.scalar_one()

    total_blocking = blocking["routes"] + blocking["keys"]
    if total_blocking > 0:
        parts = []
        if blocking["routes"]:
            parts.append(f"{blocking['routes']} 个路由")
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


async def delete_model_provider_route(db: AsyncSession, route_id: int) -> dict:
    """Delete a (model, provider) route — hard if no RequestLog references, soft otherwise.

    No blocking dependents — routes are pure routing data, not referenced by
    any other table (RequestLog references provider_id, not route_id).
    """
    # 1. Find route
    r = await db.execute(
        select(ModelProviderRoute).where(ModelProviderRoute.id == route_id)
    )
    route = r.scalar_one_or_none()
    if not route:
        raise AppException(
            status_code=404, error="渠道路由不存在", code="ROUTE_NOT_FOUND"
        )
    if route.status == "deleted":
        raise AppException(
            status_code=404, error="渠道路由不存在", code="ROUTE_NOT_FOUND"
        )

    # 2. Check RequestLog to decide hard vs soft (route_id column)
    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(
            RequestLog.route_id == route_id
        )
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        route.status = "deleted"
        if route.is_default:
            route.is_default = False
        method = "soft"
    else:
        await db.delete(route)
        method = "hard"

    await db.flush()
    logger.info("Route id=%d %s-deleted", route_id, method)
    return {"deleted": True, "method": method, "id": route_id}

"""Admin provider & key pool management router.

Endpoints:
  GET    /api/admin/providers              — list all providers (with key counts)
  GET    /api/admin/providers/dropdown     — lightweight id+name for dropdowns
  POST   /api/admin/providers              — create provider + optional initial keys
  PUT    /api/admin/providers/{id}          — update provider fields
  PATCH  /api/admin/providers/{id}/status   — toggle active / inactive
  GET    /api/admin/providers/{id}/keys     — list keys (masked)
  POST   /api/admin/providers/{id}/keys     — add keys
  DELETE /api/admin/providers/{id}/keys/{key_id} — disable a key
  PATCH  /api/admin/providers/{id}/keys/{key_id}/enable — re-enable a disabled key

All endpoints require admin authentication.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.models.provider import Provider
from app.models.user import User
from app.schemas.admin_model import ProviderOption
from app.schemas.admin_provider import (
    AdminProviderResponse,
    ProviderCreate,
    ProviderKeyCreate,
    ProviderKeyCreateResponse,
    ProviderKeyResponse,
    ProviderUpdate,
)
from app.schemas.delete import DeleteResponse
from app.services import provider_service

router = APIRouter(prefix="/api/admin/providers", tags=["admin-providers"])


# ── Provider list & dropdown ─────────────────────────────────────────


@router.get("", response_model=list[AdminProviderResponse])
async def list_providers(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all providers with key counts (admin only)."""
    return await provider_service.list_providers(db)


@router.get("/dropdown", response_model=list[ProviderOption])
async def list_providers_dropdown(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all providers for admin dropdowns (id + name only).

    Kept backward-compatible with ModelEditForm from Story 4.1.
    """
    result = await db.execute(select(Provider.id, Provider.name).order_by(Provider.name))
    rows = result.all()
    return [{"id": row[0], "name": row[1]} for row in rows]


# ── Provider CRUD ────────────────────────────────────────────────────


@router.post("", response_model=AdminProviderResponse, status_code=201)
async def create_provider(
    data: ProviderCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new provider with optional initial keys."""
    provider = await provider_service.create_provider(db, data)
    await db.commit()
    rows = await provider_service.list_providers(db)
    created = next((r for r in rows if r["id"] == provider.id), None)
    if created:
        return created
    return {
        "id": provider.id,
        "name": provider.name,
        "api_base_url": provider.api_base_url,
        "auth_header": provider.auth_header,
        "adapter": provider.adapter,
        "key_count": len(data.keys) if data.keys else 0,
        "active_key_count": len(data.keys) if data.keys else 0,
        "status": provider.status,
        "created_at": provider.created_at.isoformat(),
    }


@router.put("/{provider_id}", response_model=AdminProviderResponse)
async def update_provider(
    provider_id: int,
    data: ProviderUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update editable fields of a provider."""
    await provider_service.update_provider(db, provider_id, data)
    await db.commit()
    rows = await provider_service.list_providers(db)
    updated = next((r for r in rows if r["id"] == provider_id), None)
    if updated:
        return updated
    raise Exception("Provider updated but not found in list — should not happen")


@router.patch("/{provider_id}/status", response_model=AdminProviderResponse)
async def toggle_provider_status(
    provider_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle provider status (active ↔ inactive)."""
    await provider_service.toggle_provider_status(db, provider_id)
    await db.commit()
    rows = await provider_service.list_providers(db)
    toggled = next((r for r in rows if r["id"] == provider_id), None)
    if toggled:
        return toggled
    raise Exception("Provider status toggled but not found — should not happen")


# ── Provider Key management ──────────────────────────────────────────


@router.get("/{provider_id}/keys", response_model=list[ProviderKeyResponse])
async def list_provider_keys(
    provider_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all keys for a provider (masked — no plaintext)."""
    keys = await provider_service.get_provider_keys(db, provider_id)
    return [
        {
            "id": k.id,
            "key_prefix": k.key_prefix,
            "status": k.status,
            "created_at": k.created_at.isoformat(),
        }
        for k in keys
    ]


@router.post(
    "/{provider_id}/keys",
    response_model=ProviderKeyCreateResponse,
    status_code=201,
)
async def add_provider_keys(
    provider_id: int,
    data: ProviderKeyCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add one or more keys to an existing provider."""
    prefixes = await provider_service.add_provider_keys(
        db,
        provider_id,
        data.keys,
    )
    await db.commit()
    return {"added": len(prefixes), "key_prefixes": prefixes}


@router.delete("/{provider_id}/keys/{key_id}", status_code=204)
async def revoke_provider_key(
    provider_id: int,
    key_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Disable a provider key."""
    await provider_service.revoke_provider_key(db, key_id)
    await db.commit()


@router.patch("/{provider_id}/keys/{key_id}/enable", status_code=204)
async def enable_provider_key(
    provider_id: int,
    key_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-enable a previously disabled provider key."""
    await provider_service.enable_provider_key(db, key_id)
    await db.commit()


@router.delete("/{provider_id}", response_model=DeleteResponse)
async def delete_provider(
    provider_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a provider — hard if no request logs, soft otherwise."""
    result = await provider_service.delete_provider(db, provider_id)
    await db.commit()
    return result

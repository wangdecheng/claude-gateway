"""Admin (model ↔ provider) route management router.

The endpoint is still named /api/admin/channels for backward compatibility
with the frontend, but the underlying entity is now a ModelProviderRoute
(model binding to a provider, with a provider_model string and is_default flag).
Channel name and multiplier are managed via /api/admin/providers.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.user import User
from app.schemas.admin_channel import (
    AdminChannelResponse,
    ChannelCreate,
    ChannelUpdate,
)
from app.schemas.delete import DeleteResponse
from app.services import provider_service

logger = logging.getLogger("high-api")

router = APIRouter(prefix="/api/admin/channels", tags=["admin-channels"])


def _format_channel(result: dict) -> dict:
    """Format service-layer snake_case dict to camelCase response."""
    return {
        "id": result["id"],
        "modelId": result["model_id"],
        "modelName": result["model_name"],
        "modelStatus": result["model_status"],
        "providerId": result["provider_id"],
        "providerName": result["provider_name"],
        "providerChannelName": result["provider_channel_name"],
        "providerMultiplier": result["provider_multiplier"],
        "providerStatus": result["provider_status"],
        "providerModel": result["provider_model"],
        "isDefault": result["is_default"],
        "status": result["status"],
        "createdAt": result["created_at"],
    }


@router.get("", response_model=list[AdminChannelResponse])
async def list_channels(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all (model ↔ provider) routes for admin management."""
    routes = await provider_service.list_model_provider_routes(db)
    return [_format_channel(r) for r in routes]


@router.post("", response_model=AdminChannelResponse, status_code=201)
async def create_channel(
    data: ChannelCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new (model, provider) route."""
    try:
        result = await provider_service.create_model_provider_route(
            db,
            model_id=data.model_id,
            provider_id=data.provider_id,
            provider_model=data.provider_model,
            is_default=data.is_default,
        )
        await db.commit()
    except AppException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("create_channel failed: %s", exc)
        raise
    return _format_channel(result)


@router.put("/{channel_id}", response_model=AdminChannelResponse)
async def update_channel(
    channel_id: int,
    data: ChannelUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update provider_model and/or default flag for a route."""
    result = await provider_service.update_model_provider_route(
        db,
        channel_id,
        provider_model=data.provider_model,
        is_default=data.is_default,
    )
    await db.commit()
    return _format_channel(result)


@router.patch("/{channel_id}/status", response_model=AdminChannelResponse)
async def toggle_channel_status(
    channel_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle route status active/inactive."""
    result = await provider_service.toggle_route_status(db, channel_id)
    await db.commit()
    return _format_channel(result)


@router.delete("/{channel_id}", response_model=DeleteResponse)
async def delete_channel(
    channel_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a (model, provider) route — hard if no RequestLog references, soft otherwise."""
    result = await provider_service.delete_model_provider_route(db, channel_id)
    await db.commit()
    return result

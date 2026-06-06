"""Admin channel multiplier configuration router."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
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
        "providerStatus": result["provider_status"],
        "name": result["name"],
        "providerModelId": result["provider_model_id"],
        "multiplier": result["multiplier"],
        "isDefault": result["is_default"],
        "status": result["status"],
        "createdAt": result["created_at"],
    }


@router.get("", response_model=list[AdminChannelResponse])
async def list_channels(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all channel configurations for admin management."""
    channels = await provider_service.list_channel_configs(db)
    return [_format_channel(ch) for ch in channels]


@router.post("", response_model=AdminChannelResponse, status_code=201)
async def create_channel(
    data: ChannelCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new model-provider channel configuration."""
    try:
        result = await provider_service.create_channel_config(
            db,
            model_id=data.model_id,
            provider_id=data.provider_id,
            name=data.name,
            provider_model_id=data.provider_model_id,
            multiplier=data.multiplier,
            is_default=data.is_default,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "IntegrityError creating channel model=%d provider=%d",
            data.model_id,
            data.provider_id,
        )
        raise AppException(
            status_code=409,
            error="该供应商-模型渠道已存在",
            code="CHANNEL_ALREADY_EXISTS",
        )
    return _format_channel(result)


@router.put("/{channel_id}", response_model=AdminChannelResponse)
async def update_channel(
    channel_id: int,
    data: ChannelUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update channel name, provider_model_id, multiplier and/or default flag."""
    result = await provider_service.update_channel_config(
        db,
        channel_id,
        name=data.name,
        provider_model_id=data.provider_model_id,
        multiplier=data.multiplier,
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
    """Toggle channel status active/inactive."""
    result = await provider_service.toggle_channel_status(db, channel_id)
    await db.commit()
    return _format_channel(result)

@router.delete("/{channel_id}", response_model=DeleteResponse)
async def delete_channel(
    channel_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a channel config — hard if no request logs, soft otherwise."""
    result = await provider_service.delete_channel(db, channel_id)
    await db.commit()
    return result

"""User-side channel endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.channel import (
    ChannelModelRow,
    UserChannelInfo,
    UserChannelWithModels,
)
from app.services.channel_service import get_channel_with_models, list_active_channels

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("/active", response_model=list[UserChannelInfo])
async def list_active(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    providers = await list_active_channels(db)
    return [
        UserChannelInfo(
            id=p.id,
            channel_name=p.channel_name,
            multiplier=p.multiplier,
            is_default=False,  # per-model default; not meaningful at channel level
        )
        for p in providers
    ]


@router.get("/{provider_id}/models", response_model=UserChannelWithModels)
async def list_models(
    provider_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    provider, rows = await get_channel_with_models(db, provider_id)
    channel = UserChannelInfo(
        id=provider.id,
        channel_name=provider.channel_name,
        multiplier=provider.multiplier,
        is_default=False,
    )
    models = [
        ChannelModelRow(
            id=model.id,
            public_name=model.public_name,
            description=model.description,
            input_price=model.input_price * provider.multiplier,
            output_price=model.output_price * provider.multiplier,
            input_base_price=model.input_price,
            output_base_price=model.output_price,
        )
        for model, _route in rows
    ]
    return UserChannelWithModels(channel=channel, models=models)

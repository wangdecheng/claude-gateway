from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.model import ModelDetail, ModelWithChannels
from app.services.model_service import get_model_detail, list_active_models

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get(
    "",
    response_model=list[ModelWithChannels],
)
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active models with their channel configurations."""
    models = await list_active_models(db)
    return [
        {
            "id": m["id"],
            "publicName": m["public_name"],
            "description": m.get("description"),
            "inputPrice": m["input_price"],
            "outputPrice": m["output_price"],
            "channels": [
                {
                    "id": ch["id"],
                    "providerName": ch["provider_name"],
                    "channelName": ch["channel_name"],
                    "multiplier": ch["multiplier"],
                    "isDefault": ch["is_default"],
                }
                for ch in m["channels"]
            ],
        }
        for m in models
    ]


@router.get(
    "/{model_id}",
    response_model=ModelDetail,
)
async def model_detail(
    model_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information for a single model."""
    detail = await get_model_detail(db, model_id)
    return {
        "id": detail["id"],
        "publicName": detail["public_name"],
        "providerName": detail["provider_name"],
        "providerModelId": detail["provider_model_id"],
        "description": detail.get("description"),
        "inputPrice": detail["input_price"],
        "outputPrice": detail["output_price"],
        "status": detail["status"],
        "channels": [
            {
                "id": ch["id"],
                "providerName": ch["provider_name"],
                "channelName": ch["channel_name"],
                "multiplier": ch["multiplier"],
                "isDefault": ch["is_default"],
            }
            for ch in detail["channels"]
        ],
        "createdAt": str(detail["created_at"]),
    }

"""Admin model management router — prefix /api/admin/models."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.models.user import User
from app.schemas.admin_model import AdminModelResponse, ModelCreate, ModelUpdate
from app.schemas.delete import DeleteResponse
from app.services import model_service

router = APIRouter(prefix="/api/admin/models", tags=["admin-models"])


def _format_admin_model(result: dict) -> dict:
    """Format service-layer dict to camelCase response matching AdminModelResponse."""
    return {
        "id": result["id"],
        "publicName": result["public_name"],
        "description": result.get("description"),
        "inputPrice": result["input_price"],
        "outputPrice": result["output_price"],
        "status": result["status"],
        "createdAt": result["created_at"],
    }


@router.get(
    "",
    response_model=list[AdminModelResponse],
)
async def list_models(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all models (including inactive) for admin management."""
    models = await model_service.list_all_models(db)
    return [_format_admin_model(m) for m in models]


@router.post(
    "",
    response_model=AdminModelResponse,
    status_code=201,
)
async def create_model(
    data: ModelCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a new model."""
    result = await model_service.create_model(
        db,
        public_name=data.public_name,
        description=data.description,
        input_price=data.input_price,
        output_price=data.output_price,
    )
    await db.commit()
    return _format_admin_model(result)


@router.put(
    "/{model_id}",
    response_model=AdminModelResponse,
)
async def update_model(
    model_id: int,
    data: ModelUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update model fields."""
    result = await model_service.update_model(
        db,
        model_id,
        public_name=data.public_name,
        description=data.description,
        input_price=data.input_price,
        output_price=data.output_price,
    )
    await db.commit()
    return _format_admin_model(result)


@router.patch(
    "/{model_id}/status",
    response_model=AdminModelResponse,
)
async def toggle_model_status(
    model_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle model status (active ↔ inactive)."""
    result = await model_service.toggle_model_status(db, model_id)
    await db.commit()
    return _format_admin_model(result)

@router.delete(
    "/{model_id}",
    response_model=DeleteResponse,
)
async def delete_model(
    model_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a model — hard if no request logs, soft otherwise."""
    result = await model_service.delete_model(db, model_id)
    await db.commit()
    return result

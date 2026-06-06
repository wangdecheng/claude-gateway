"""GET /v1/models — Anthropic-compatible model discovery."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user_from_api_key
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
from app.models.provider import Provider
from app.models.user import User
from app.schemas.common import ErrorResponse
from app.schemas.v1_models import ListModelsResponse, ModelData

router = APIRouter(prefix="/v1", tags=["v1"])


def _to_display_name(public_name: str) -> str:
    """Convert 'claude-opus-4-8' → 'Claude Opus 4.8'.

    Words starting with a letter get their first character uppercased.
    Consecutive numeric segments (e.g. "4", "8") are joined with dots.
    """
    parts = public_name.split("-")
    result: list[str] = []
    pending_digits: list[str] = []

    for word in parts:
        # Check if this segment is purely numeric (or starts with a digit like "4o")
        if word and word[0].isdigit():
            pending_digits.append(word)
        else:
            # Flush any accumulated digit segments as a dot-joined group
            if pending_digits:
                result.append(".".join(pending_digits))
                pending_digits = []
            # Capitalize alpha-leading word
            if word:
                result.append(word[0].upper() + word[1:])

    # Flush trailing digits
    if pending_digits:
        result.append(".".join(pending_digits))

    return " ".join(result)


async def _get_active_models(db: AsyncSession) -> list[ModelData]:
    """Return all active models that have at least one valid channel config.

    A model is considered 'available' when:
      1. models.status = 'active'
      2. Has ≥1 channel_config with status='active', multiplier > 0
      3. That channel_config's provider has status='active'

    Models whose provider is inactive are still included but marked with
    provider_status='inactive' so clients can display a "已停用" indicator.
    """
    # Get models with valid channels (DISTINCT to avoid duplicates from multiple channels).
    # Includes models from inactive providers with provider_status marker per AC-5.
    result = await db.execute(
        select(Model, Provider.status.label("provider_status"))
        .distinct()
        .join(ChannelConfig, ChannelConfig.model_id == Model.id)
        .join(Provider, Provider.id == ChannelConfig.provider_id)
        .where(
            Model.status == "active",
            ChannelConfig.status == "active",
            ChannelConfig.multiplier > 0,
        )
        .order_by(Model.public_name)
    )
    rows = result.all()

    if not rows:
        return []

    return [
        ModelData(
            id=model.public_name,
            display_name=_to_display_name(model.public_name),
            created_at=model.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if model.created_at else "",
            provider_status=provider_status,
        )
        for model, provider_status in rows
    ]


@router.get(
    "/models",
    response_model=ListModelsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Authentication failed"},
    },
)
async def list_models(
    auth: tuple[User, ApiKey] = Depends(get_current_user_from_api_key),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/models — Anthropic-compatible model discovery.

    Returns all active models with valid channel configurations.
    Authenticated via Bearer sk header.

    Response format matches Anthropic's Models List API:
        https://docs.anthropic.com/en/api/models-list
    """
    user, api_key = auth  # noqa: F841 — auth validates sk, user not needed for listing

    models = await _get_active_models(db)

    return ListModelsResponse(
        data=models,
        has_more=False,
        first_id=models[0].id if models else None,
        last_id=models[-1].id if models else None,
    )

"""Read queries for the user-side channel endpoints."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppException
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.provider import Provider


async def list_active_channels(db: AsyncSession) -> list[Provider]:
    """All active providers (the user-facing channel list)."""
    result = await db.execute(
        select(Provider)
        .where(Provider.status == "active")
        .order_by(Provider.channel_name)
    )
    return list(result.scalars().all())


async def get_channel_with_models(
    db: AsyncSession, provider_id: int
) -> tuple[Provider, list[tuple[Model, ModelProviderRoute]]]:
    """Return a provider and its (model, route) pairs, or 404."""
    p = await db.execute(select(Provider).where(Provider.id == provider_id))
    provider = p.scalar_one_or_none()
    if not provider or provider.status != "active":
        raise AppException(status_code=404, error="渠道不存在", code="CHANNEL_NOT_FOUND")

    rows = await db.execute(
        select(Model, ModelProviderRoute)
        .join(ModelProviderRoute, ModelProviderRoute.model_id == Model.id)
        .where(
            ModelProviderRoute.provider_id == provider_id,
            Model.status == "active",
        )
        .order_by(Model.public_name)
    )
    return provider, list(rows.all())

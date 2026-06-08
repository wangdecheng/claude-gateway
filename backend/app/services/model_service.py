import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppException
from app.models.model import ChannelConfig, Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.provider import Provider
from app.models.request_log import RequestLog

logger = logging.getLogger("high-api")


def _normalize_default_channels(channels: list[dict]) -> list[dict]:
    """Sort channels and ensure exactly one runtime default when possible.

    If DB has no default, the lowest multiplier active channel becomes the
    response-level default without writing to the database.
    """
    if not channels:
        return channels

    default_channels = [channel for channel in channels if channel["is_default"]]
    if default_channels:
        default_channels.sort(key=lambda c: c["multiplier"])
        chosen_default_id = default_channels[0]["id"]
        for channel in channels:
            channel["is_default"] = channel["id"] == chosen_default_id
        channels.sort(key=lambda c: (not c["is_default"], c["multiplier"]))
        return channels

    channels.sort(key=lambda c: c["multiplier"])
    channels[0]["is_default"] = True
    return channels


async def list_active_models(db: AsyncSession) -> list[dict]:
    """Return all active models with their channel configurations.

    Each model includes a list of channels (channel_name, multiplier, is_default).
    Models with status != 'active' are excluded.
    """
    model_result = await db.execute(
        select(Model).where(Model.status == "active").order_by(Model.public_name)
    )
    models = model_result.scalars().all()

    if not models:
        return []

    model_ids = [m.id for m in models]
    channel_result = await db.execute(
        select(ModelProviderRoute, Provider)
        .join(Provider, Provider.id == ModelProviderRoute.provider_id)
        .where(
            ModelProviderRoute.model_id.in_(model_ids),
            Provider.status == "active",
            Provider.multiplier > 0,
        )
    )
    channel_rows = channel_result.all()

    channels_by_model: dict[int, list[dict]] = {}
    for route, prov in channel_rows:
        channels_by_model.setdefault(route.model_id, []).append(
            {
                "id": prov.id,
                "model_id": route.model_id,
                "channel_name": prov.channel_name,
                "multiplier": prov.multiplier,
                "is_default": route.is_default,
            }
        )

    result = []
    for model in models:
        channels = channels_by_model.get(model.id, [])
        if not channels:
            logger.warning(
                "Model %s (id=%d) hidden: no active channels",
                model.public_name,
                model.id,
            )
            continue
        channels = _normalize_default_channels(channels)
        result.append(
            {
                "id": model.id,
                "public_name": model.public_name,
                "description": model.description,
                "input_price": model.input_price,
                "output_price": model.output_price,
                "channels": [
                    {
                        "id": channel["id"],
                        "channel_name": channel["channel_name"],
                        "multiplier": channel["multiplier"],
                        "is_default": channel["is_default"],
                    }
                    for channel in channels
                ],
            }
        )

    return result


async def get_model_detail(db: AsyncSession, model_id: int) -> dict:
    """Return full detail for a single model, including all channels."""
    result = await db.execute(select(Model).where(Model.id == model_id, Model.status == "active"))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    channel_result = await db.execute(
        select(ModelProviderRoute, Provider)
        .join(Provider, Provider.id == ModelProviderRoute.provider_id)
        .where(
            ModelProviderRoute.model_id == model.id,
            Provider.status == "active",
            Provider.multiplier > 0,
        )
    )
    channel_rows = channel_result.all()

    channels = []
    for route, prov in channel_rows:
        channels.append(
            {
                "id": prov.id,
                "channel_name": prov.channel_name,
                "multiplier": prov.multiplier,
                "is_default": route.is_default,
            }
        )
    channels = _normalize_default_channels(channels)
    if not channels:
        raise AppException(
            status_code=404, error="该模型暂无可用的供应商渠道", code="MODEL_NO_ACTIVE_CHANNELS"
        )

    return {
        "id": model.id,
        "public_name": model.public_name,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "status": model.status,
        "channels": channels,
        "created_at": model.created_at,
    }


# --- Admin model management ---


async def list_all_models(db: AsyncSession) -> list[dict]:
    """Return all models (including inactive) for admin.

    Sorted by created_at descending. No provider join — provider info is
    available through the channels endpoint.
    """
    result = await db.execute(
        select(Model)
        .where(Model.status != "deleted")
        .order_by(Model.created_at.desc())
    )
    models = result.scalars().all()

    return [
        {
            "id": model.id,
            "public_name": model.public_name,
            "description": model.description,
            "input_price": model.input_price,
            "output_price": model.output_price,
            "status": model.status,
            "created_at": model.created_at.isoformat(),
        }
        for model in models
    ]


async def create_model(
    db: AsyncSession,
    *,
    public_name: str,
    description: str | None,
    input_price: int,
    output_price: int,
) -> dict:
    """Create a new model. No provider or channel configuration — that's done separately."""
    existing = await db.execute(select(Model.id).where(Model.public_name == public_name))
    if existing.scalar_one_or_none():
        raise AppException(
            status_code=409,
            error="模型名称已存在",
            code="MODEL_NAME_EXISTS",
        )

    model = Model(
        public_name=public_name,
        description=description,
        input_price=input_price,
        output_price=output_price,
        status="active",
    )
    db.add(model)
    await db.flush()
    await db.refresh(model)

    return {
        "id": model.id,
        "public_name": model.public_name,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "status": model.status,
        "created_at": model.created_at.isoformat(),
    }


async def update_model(
    db: AsyncSession,
    model_id: int,
    *,
    public_name: str | None = None,
    description: str | None = None,
    input_price: int | None = None,
    output_price: int | None = None,
) -> dict:
    """Update model fields. No provider or multiplier — those are channel-level concerns."""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    if public_name is not None and public_name != model.public_name:
        existing = await db.execute(
            select(Model.id).where(
                Model.public_name == public_name,
                Model.id != model_id,
            )
        )
        if existing.scalar_one_or_none():
            raise AppException(
                status_code=409,
                error="模型名称已存在",
                code="MODEL_NAME_EXISTS",
            )
        model.public_name = public_name

    if description is not None:
        model.description = description
    if input_price is not None:
        model.input_price = input_price
    if output_price is not None:
        model.output_price = output_price

    await db.flush()
    await db.refresh(model)

    return {
        "id": model.id,
        "public_name": model.public_name,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "status": model.status,
        "created_at": model.created_at.isoformat(),
    }


async def toggle_model_status(db: AsyncSession, model_id: int) -> dict:
    """Toggle model status between 'active' and 'inactive'."""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    if model.status == "active":
        model.status = "inactive"
    elif model.status == "inactive":
        model.status = "active"
    else:
        raise AppException(
            status_code=400,
            error="无效的模型状态",
            code="INVALID_MODEL_STATUS",
        )
    await db.flush()
    await db.refresh(model)

    return {
        "id": model.id,
        "public_name": model.public_name,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "status": model.status,
        "created_at": model.created_at.isoformat(),
    }


async def delete_model(db: AsyncSession, model_id: int) -> dict:
    """Delete a model — hard if no RequestLog references, soft otherwise.

    Blocked if ChannelConfig records still reference this model.
    """
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")
    if model.status == "deleted":
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    ch_count_result = await db.execute(
        select(func.count(ChannelConfig.id)).where(ChannelConfig.model_id == model_id)
    )
    channel_count = ch_count_result.scalar_one()
    if channel_count > 0:
        raise AppException(
            status_code=409,
            error=f"无法删除：该模型下有 {channel_count} 个渠道配置，请先删除关联渠道",
            code="HAS_DEPENDENTS",
        )

    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.model_id == model_id)
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        model.status = "deleted"
        method = "soft"
    else:
        await db.delete(model)
        method = "hard"

    await db.flush()
    logger.info(
        "Model id=%d (%s) %s-deleted",
        model_id,
        model.public_name if has_request_logs else "",
        method,
    )
    return {"deleted": True, "method": method, "id": model_id}

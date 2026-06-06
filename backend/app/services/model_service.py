import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppException
from app.models.model import ChannelConfig, Model
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
        # Deterministic: lowest-multiplier default wins when multiple exist
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

    Each model includes a list of channels (provider_name, multiplier, is_default).
    Models with status != 'active' are excluded.
    """
    # Fetch all active models
    model_result = await db.execute(
        select(Model).where(Model.status == "active").order_by(Model.public_name)
    )
    models = model_result.scalars().all()

    if not models:
        return []

    # Fetch all channels for these models in one query
    model_ids = [m.id for m in models]
    channel_result = await db.execute(
        select(ChannelConfig, Provider.name)
        .join(Provider, ChannelConfig.provider_id == Provider.id)
        .where(
            ChannelConfig.model_id.in_(model_ids),
            ChannelConfig.status == "active",
            Provider.status == "active",
            ChannelConfig.multiplier > 0,
        )
    )
    channel_rows = channel_result.all()

    # Group channels by model_id
    channels_by_model: dict[int, list[dict]] = {}
    for ch_config, provider_name in channel_rows:
        channels_by_model.setdefault(ch_config.model_id, []).append(
            {
                "id": ch_config.id,
                "model_id": ch_config.model_id,
                "provider_name": provider_name,
                "multiplier": ch_config.multiplier,
                "is_default": ch_config.is_default,
            }
        )

    default_counts: dict[int, int] = {}
    for channels in channels_by_model.values():
        for channel in channels:
            if channel["is_default"]:
                default_counts[channel["model_id"]] = default_counts.get(channel["model_id"], 0) + 1

    # Assemble response
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
                        "provider_name": channel["provider_name"],
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

    # Get native provider name
    provider_result = await db.execute(
        select(Provider.name).where(Provider.id == model.provider_id, Provider.status == "active")
    )
    provider_name = provider_result.scalar_one_or_none()
    if not provider_name:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    # Get all channels
    channel_result = await db.execute(
        select(ChannelConfig, Provider.name)
        .join(Provider, ChannelConfig.provider_id == Provider.id)
        .where(
            ChannelConfig.model_id == model.id,
            ChannelConfig.status == "active",
            Provider.status == "active",
            ChannelConfig.multiplier > 0,
        )
    )
    channel_rows = channel_result.all()

    channels = []
    for ch_config, ch_provider_name in channel_rows:
        channels.append(
            {
                "id": ch_config.id,
                "provider_name": ch_provider_name,
                "multiplier": ch_config.multiplier,
                "is_default": ch_config.is_default,
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
        "provider_name": provider_name,
        "provider_model_id": model.provider_model_id,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "status": model.status,
        "channels": channels,
        "created_at": model.created_at,
    }


# --- Admin model management ---


async def list_all_models(db: AsyncSession) -> list[dict]:
    """Return all models (including inactive) for admin, with provider name, status and default multiplier.

    Sorted by created_at descending. Uses a subquery to avoid duplicate rows
    when a model has multiple default ChannelConfigs.
    """

    # Correlated scalar subquery: portable across SQLite/PostgreSQL/MySQL.
    # Picks the lowest default multiplier when multiple defaults exist.
    default_mult = (
        select(ChannelConfig.multiplier)
        .where(
            ChannelConfig.model_id == Model.id,
            ChannelConfig.is_default,
        )
        .order_by(ChannelConfig.multiplier.asc())
        .limit(1)
        .correlate(Model)
        .scalar_subquery()
    )

    result = await db.execute(
        select(Model, Provider.name, Provider.status, default_mult)
        .join(Provider, Model.provider_id == Provider.id)
        .where(Model.status != "deleted")
        .order_by(Model.created_at.desc())
    )
    rows = result.all()

    result = []
    for model, provider_name, provider_status, multiplier in rows:
        if multiplier is None:
            logger.warning(
                "Model %s (id=%d) has no default ChannelConfig in admin list",
                model.public_name,
                model.id,
            )
        result.append(
            {
                "id": model.id,
                "public_name": model.public_name,
                "provider_id": model.provider_id,
                "provider_name": provider_name,
                "provider_status": provider_status,
                "provider_model_id": model.provider_model_id,
                "description": model.description,
                "input_price": model.input_price,
                "output_price": model.output_price,
                "multiplier": multiplier if multiplier is not None else 1.0,
                "status": model.status,
                "created_at": model.created_at.isoformat(),
            }
        )
    return result


async def create_model(
    db: AsyncSession,
    *,
    public_name: str,
    provider_id: int,
    provider_model_id: str,
    description: str | None,
    input_price: int,
    output_price: int,
    multiplier: float,
) -> dict:
    """Create a new model with a default ChannelConfig in a transaction."""
    # 1. Check public_name uniqueness
    existing = await db.execute(select(Model.id).where(Model.public_name == public_name))
    if existing.scalar_one_or_none():
        raise AppException(
            status_code=409,
            error="模型名称已存在",
            code="MODEL_NAME_EXISTS",
        )

    # 2. Validate multiplier first (cheap validation before DB queries)
    if multiplier <= 0:
        raise AppException(
            status_code=400,
            error="倍率必须大于 0",
            code="INVALID_MULTIPLIER",
        )

    # 3. Validate provider exists and is active
    provider_result = await db.execute(
        select(Provider.name, Provider.status).where(Provider.id == provider_id)
    )
    provider_row = provider_result.one_or_none()
    if not provider_row:
        raise AppException(
            status_code=400,
            error="供应商不存在",
            code="PROVIDER_NOT_FOUND",
        )
    provider_name, provider_status = provider_row
    if provider_status != "active":
        raise AppException(
            status_code=400,
            error="供应商未启用",
            code="PROVIDER_INACTIVE",
        )

    # 4. INSERT Model
    model = Model(
        public_name=public_name,
        provider_id=provider_id,
        provider_model_id=provider_model_id,
        description=description,
        input_price=input_price,
        output_price=output_price,
        status="active",
    )
    db.add(model)
    await db.flush()  # Get model.id

    # 5. INSERT default ChannelConfig
    channel = ChannelConfig(
        model_id=model.id,
        provider_id=provider_id,
        multiplier=multiplier,
        is_default=True,
        status="active",
    )
    db.add(channel)
    await db.flush()
    await db.refresh(model)

    return {
        "id": model.id,
        "public_name": model.public_name,
        "provider_id": model.provider_id,
        "provider_name": provider_name,
        "provider_model_id": model.provider_model_id,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "multiplier": multiplier,
        "status": model.status,
        "created_at": model.created_at.isoformat(),
    }


async def update_model(
    db: AsyncSession,
    model_id: int,
    *,
    public_name: str | None = None,
    provider_id: int | None = None,
    provider_model_id: str | None = None,
    description: str | None = None,
    input_price: int | None = None,
    output_price: int | None = None,
    multiplier: float | None = None,
) -> dict:
    """Update model fields. Optionally update the default channel multiplier."""
    # Fetch model (including inactive)
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    # Check public_name uniqueness if changing
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

    if provider_id is not None:
        # Validate new provider exists and is active
        prov_result = await db.execute(
            select(Provider.id, Provider.status).where(Provider.id == provider_id)
        )
        prov_row = prov_result.one_or_none()
        if not prov_row:
            raise AppException(
                status_code=400,
                error="供应商不存在",
                code="PROVIDER_NOT_FOUND",
            )
        if prov_row.status != "active":
            raise AppException(
                status_code=400,
                error="供应商未启用",
                code="PROVIDER_INACTIVE",
            )
        model.provider_id = provider_id
    if provider_model_id is not None:
        model.provider_model_id = provider_model_id
    if description is not None:
        model.description = description
    if input_price is not None:
        model.input_price = input_price
    if output_price is not None:
        model.output_price = output_price

    # Update default channel multiplier if provided
    if multiplier is not None:
        if multiplier <= 0:
            raise AppException(
                status_code=400,
                error="倍率必须大于 0",
                code="INVALID_MULTIPLIER",
            )
        ch_result = await db.execute(
            select(ChannelConfig).where(
                ChannelConfig.model_id == model_id,
                ChannelConfig.is_default,
            )
        )
        default_ch = ch_result.scalar_one_or_none()
        if not default_ch:
            raise AppException(
                status_code=400,
                error="没有默认渠道可更新倍率",
                code="NO_DEFAULT_CHANNEL",
            )
        default_ch.multiplier = multiplier

    await db.flush()
    await db.refresh(model)

    # Fetch provider name and multiplier for response
    provider_result = await db.execute(
        select(Provider.name).where(Provider.id == model.provider_id)
    )
    provider_name = provider_result.scalar_one_or_none()
    provider_name = provider_name if provider_name is not None else ""

    mult_result = await db.execute(
        select(ChannelConfig.multiplier).where(
            ChannelConfig.model_id == model_id,
            ChannelConfig.is_default,
        )
    )
    raw_multiplier = mult_result.scalar_one_or_none()
    current_multiplier = raw_multiplier if raw_multiplier is not None else 1.0

    return {
        "id": model.id,
        "public_name": model.public_name,
        "provider_id": model.provider_id,
        "provider_name": provider_name,
        "provider_model_id": model.provider_model_id,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "multiplier": current_multiplier,
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

    # Fetch provider name and default multiplier for response
    provider_result = await db.execute(
        select(Provider.name).where(Provider.id == model.provider_id)
    )
    provider_name = provider_result.scalar_one_or_none()
    provider_name = provider_name if provider_name is not None else ""

    mult_result = await db.execute(
        select(ChannelConfig.multiplier).where(
            ChannelConfig.model_id == model_id,
            ChannelConfig.is_default,
        )
    )
    raw_multiplier = mult_result.scalar_one_or_none()
    current_multiplier = raw_multiplier if raw_multiplier is not None else 1.0

    return {
        "id": model.id,
        "public_name": model.public_name,
        "provider_id": model.provider_id,
        "provider_name": provider_name,
        "provider_model_id": model.provider_model_id,
        "description": model.description,
        "input_price": model.input_price,
        "output_price": model.output_price,
        "multiplier": current_multiplier,
        "status": model.status,
        "created_at": model.created_at.isoformat(),
    }


async def delete_model(db: AsyncSession, model_id: int) -> dict:
    """Delete a model — hard if no RequestLog references, soft otherwise.

    Blocked if ChannelConfig records still reference this model.
    """
    # 1. Find model
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")
    if model.status == "deleted":
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    # 2. Check blocking dependents: ChannelConfig
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

    # 3. Check RequestLog references to decide hard vs soft
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

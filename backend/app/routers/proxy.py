"""POST /v1/messages — Anthropic-compatible chat proxy with streaming billing."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, get_provider_registry, require_api_key
from api.model_router import ModelRouter
from api.models.anthropic import MessagesRequest
from app.exceptions import AppException
from app.models.model import Model
from app.models.provider import Provider, ProviderKey
from app.models.user import User
from config.settings import get_settings
from core.anthropic.sse import ANTHROPIC_SSE_RESPONSE_HEADERS
from providers.registry import ProviderRegistry

logger = logging.getLogger("cloude-gateway.proxy")

router = APIRouter(tags=["proxy"])

# Maximum cost cap: 200 RMB (20000 cents) per request
MAX_COST_CENTS = 20_000
# Minimum balance threshold for pre-flight check
MIN_BALANCE_THRESHOLD_CENTS = 100  # ¥1.00


async def _lookup_model(db: AsyncSession, model_name: str) -> Model | None:
    result = await db.execute(
        select(Model).where(Model.public_name == model_name, Model.status == "active")
    )
    return result.scalar_one_or_none()


async def _get_active_upstream_key(
    db: AsyncSession, provider_id: int, channel_id: int | None = None
) -> str | None:
    """Get an active upstream API key. If channel_id is set, select from channel_keys subset."""
    from app.services.provider_service import decrypt_api_key

    if channel_id:
        from app.models.channel_key import ChannelKey

        result = await db.execute(
            select(ProviderKey)
            .join(ChannelKey, ChannelKey.provider_key_id == ProviderKey.id)
            .where(
                ChannelKey.channel_id == channel_id,
                ProviderKey.provider_id == provider_id,
                ProviderKey.status == "active",
            )
        )
        keys = result.scalars().all()
    else:
        result = await db.execute(
            select(ProviderKey).where(
                ProviderKey.provider_id == provider_id,
                ProviderKey.status == "active",
            )
        )
        keys = result.scalars().all()

    if not keys:
        return None
    return decrypt_api_key(keys[0].key_encrypted, provider_id=provider_id)


@router.post("/v1/messages")
async def create_message(
    request: Request,
    body: MessagesRequest,
    auth: tuple = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
    registry: ProviderRegistry = Depends(get_provider_registry),
):
    """Anthropic-compatible messages endpoint with streaming billing."""
    user, api_key = auth
    settings = get_settings()

    # ── 1. Resolve model from DB ──────────────────────────────
    router_ = ModelRouter(settings, db=db)
    routed = await router_.resolve_from_db(body.model)

    if routed.db_model_id is None:
        raise AppException(
            status_code=400, error=f"不支持的模型: {body.model}", code="UNSUPPORTED_MODEL"
        )

    # ── 2. Get model for pricing ──────────────────────────────
    model = await _lookup_model(db, body.model)
    if not model:
        raise AppException(
            status_code=400, error=f"不支持的模型: {body.model}", code="UNSUPPORTED_MODEL"
        )

    # ── 3. Get provider ───────────────────────────────────────
    provider_result = await db.execute(select(Provider).where(Provider.id == routed.db_provider_id))
    provider = provider_result.scalar_one_or_none()
    if not provider or provider.status != "active":
        raise AppException(status_code=500, error="上游提供商不可用", code="PROVIDER_UNAVAILABLE")

    # ── 4. Get upstream API key from key pool ─────────────────
    upstream_api_key = await _get_active_upstream_key(
        db, provider.id, channel_id=routed.db_channel_id
    )
    if not upstream_api_key:
        raise AppException(status_code=500, error="上游服务配置错误", code="UPSTREAM_CONFIG_ERROR")

    # ── 5. Pre-flight balance check ───────────────────────────
    if user.balance < MIN_BALANCE_THRESHOLD_CENTS:
        raise AppException(
            status_code=402,
            error=f"余额不足，最低余额要求 ¥{MIN_BALANCE_THRESHOLD_CENTS / 100:.2f}",
            code="INSUFFICIENT_BALANCE",
        )

    # ── 6. Estimate max cost, pre-reserve ─────────────────────
    estimated_cost = int((body.max_tokens or 4096) * model.output_price / 1000 / 10000)
    estimated_cost = min(estimated_cost, MAX_COST_CENTS)

    # Lock user row
    lock_result = await db.execute(select(User.balance).where(User.id == user.id).with_for_update())
    locked_balance = lock_result.scalar_one()
    reserve_amount = min(estimated_cost, locked_balance)
    user.balance = locked_balance - reserve_amount
    await db.flush()

    # ── 7. Get or create provider instance ────────────────────
    provider_instance = registry.get(
        routed.resolved.provider_id,
        api_key=upstream_api_key,
        base_url=provider.api_base_url or None,
    )

    # ── 8. Store provider on request.state for api/routes.py resolution ──
    request.state.active_provider = provider_instance

    # ── 9. Stream response, accumulate usage ──────────────────
    from app.services.billing_service import compute_cost
    from app.services.usage_service import record_usage

    accumulated_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}

    async def billing_stream():
        nonlocal accumulated_usage
        try:
            async for chunk in provider_instance.stream_response(
                body,
                request_id=f"req_{body.model}",
            ):
                yield chunk
        finally:
            # Extract usage from accumulated SSE events
            input_tokens = accumulated_usage["input_tokens"] or 100
            output_tokens = accumulated_usage["output_tokens"] or 0
            cache_read_tokens = accumulated_usage["cache_read_tokens"] or 0

            actual_cost = compute_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_price_micro_yuan=model.input_price,
                output_price_micro_yuan=model.output_price,
                cache_read_tokens=cache_read_tokens,
                cache_read_price_micro_yuan=model.cache_read_price,
                channel_multiplier=1.0,
            )
            actual_cost = min(actual_cost, MAX_COST_CENTS)

            # Deduct actual cost
            user.balance = locked_balance - actual_cost

            await record_usage(
                db=db,
                user_id=user.id,
                api_key_id=api_key.id,
                model=body.model,
                request_tokens=input_tokens,
                response_tokens=output_tokens,
                cost_cents=actual_cost,
            )

            await db.commit()
            logger.info(
                "Billing settled: user=%d model=%s input=%d output=%d cost=%d cents balance=%d",
                user.id,
                body.model,
                input_tokens,
                output_tokens,
                actual_cost,
                user.balance,
            )

    return StreamingResponse(
        billing_stream(),
        media_type="text/event-stream",
        headers=ANTHROPIC_SSE_RESPONSE_HEADERS,
    )

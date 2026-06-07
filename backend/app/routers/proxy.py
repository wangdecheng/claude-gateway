"""POST /v1/messages — Anthropic-compatible chat proxy with streaming billing."""

import json
import logging
import uuid

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
from config.settings import get_settings
from core.anthropic.sse import ANTHROPIC_SSE_RESPONSE_HEADERS
from core.trace import trace_event
from providers.registry import ProviderRegistry

logger = logging.getLogger("cloude-gateway.proxy")

router = APIRouter(tags=["proxy"])

# Minimum balance threshold for pre-flight check (¥0.10)
MIN_BALANCE_THRESHOLD_CENTS = 10


def _extract_usage_from_sse_line(line: str) -> dict[str, int] | None:
    """Parse usage from message_start / message_delta data lines in the SSE stream."""
    if not line.startswith("data:"):
        return None
    try:
        payload = json.loads(line.removeprefix("data:").strip())
    except json.JSONDecodeError:
        return None

    event_type = payload.get("type")
    if event_type not in ("message_start", "message_delta"):
        return None

    result = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }

    if event_type == "message_start":
        msg = payload.get("message", {})
        usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
        result["input_tokens"] = usage.get("input_tokens", 0)
        result["cache_read_tokens"] = usage.get("cache_read_input_tokens", 0)
        result["cache_creation_tokens"] = usage.get("cache_creation_input_tokens", 0)
    elif event_type == "message_delta":
        usage = payload.get("usage", {})
        if isinstance(usage, dict):
            result["output_tokens"] = usage.get("output_tokens", 0)
            # DeepSeek provider normalizer may inject cache fields into delta events
            result["cache_read_tokens"] = usage.get("cache_read_input_tokens", 0)
            result["cache_creation_tokens"] = usage.get("cache_creation_input_tokens", 0)

    return result


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
    if not channel_id or not keys:
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

    # ── 6. Get or create provider instance ────────────────────
    trace_event(
        stage="routing",
        event="proxy.provider.resolve_start",
        source="api",
        provider_id=routed.provider_id,
        model=body.model,
    )
    provider_instance = registry.get(
        routed.provider_id,
        api_key=upstream_api_key,
        base_url=provider.api_base_url or None,
    )
    provider_body = body.model_copy(update={"model": routed.provider_model}, deep=True)

    # ── 7. Store provider on request.state for api/routes.py resolution ──
    request.state.active_provider = provider_instance

    # ── 8. Stream response, accumulate usage ──────────────────
    accumulated_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }
    user_id = user.id
    api_key_id = api_key.id

    _provider_model = routed.provider_model
    _original_model = body.model
    _remap_model = _provider_model != _original_model

    async def billing_stream():
        nonlocal accumulated_usage
        try:
            trace_event(
                stage="egress",
                event="proxy.stream.start",
                source="api",
                provider_id=routed.provider_id,
                gateway_model=body.model,
                provider_model=routed.provider_model,
            )
            async for chunk in provider_instance.stream_response(
                provider_body,
                request_id=f"req_{body.model}",
            ):
                # Parse usage from message_start / message_delta data lines
                usage = _extract_usage_from_sse_line(chunk)
                if usage:
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_tokens",
                        "cache_creation_tokens",
                    ):
                        val = usage.get(key, 0)
                        if val:
                            accumulated_usage[key] = val
                if _remap_model:
                    yield chunk.replace(_provider_model, _original_model)
                else:
                    yield chunk
        finally:
            input_tokens = accumulated_usage["input_tokens"] or 0
            output_tokens = accumulated_usage["output_tokens"] or 0
            cache_read_tokens = accumulated_usage["cache_read_tokens"] or 0
            cache_creation_tokens = accumulated_usage["cache_creation_tokens"] or 0
            try:
                from app.services.billing.pending import write_pending_billing
                await write_pending_billing(
                    db,
                    request_id=uuid.uuid4(),
                    user_id=user_id,
                    api_key_id=api_key_id,
                    model_id=model.id,
                    channel_id=routed.db_channel_id,
                    provider_id=provider.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "Failed to write pending_billing for user=%d model=%s",
                    user_id, body.model,
                )

    # Release the request-scoped transaction before the long-lived stream starts;
    # the finally block in billing_stream will start a fresh transaction for the
    # pending_billing write.
    await db.commit()

    return StreamingResponse(
        billing_stream(),
        media_type="text/event-stream",
        headers=ANTHROPIC_SSE_RESPONSE_HEADERS,
    )

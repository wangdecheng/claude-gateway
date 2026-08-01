"""POST /v1/messages — Anthropic-compatible chat proxy with streaming billing."""

import json
import logging
import uuid

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, get_provider_registry, require_api_key
from api.model_router import ModelRouter
from api.models.anthropic import MessagesRequest
from app.exceptions import AppException
from app.models.model import Model
from app.models.provider import Provider, ProviderKey
from app.services.billing.token_coefficient import apply_coefficient
from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event
from config.settings import get_settings
from core.anthropic.sse import ANTHROPIC_SSE_RESPONSE_HEADERS
from core.trace import trace_event
from providers.exceptions import APIError, UpstreamResponseError
from providers.registry import ProviderRegistry

logger = logging.getLogger("cloude-gateway.proxy")

router = APIRouter(tags=["proxy"])

# Minimum balance threshold for pre-flight check (¥0.10)
MIN_BALANCE_THRESHOLD_CENTS = 10

_UPSTREAM_ERROR_HEADERS = frozenset({"content-type", "retry-after"})


def _is_upstream_request_trace_header(name: str) -> bool:
    lower = name.lower()
    return lower in {"request-id", "traceparent", "tracestate"} or lower.endswith(
        ("-request-id", "-trace-id")
    )


def _passthrough_upstream_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep response metadata needed for error parsing, retrying, and correlation."""
    return {
        name: value
        for name, value in headers.items()
        if name.lower() in _UPSTREAM_ERROR_HEADERS or _is_upstream_request_trace_header(name)
    }


def _sse_error_chunk_state(chunk: str, in_error_event: bool) -> tuple[bool, bool]:
    """Return whether a chunk belongs to an upstream SSE error event and its next state."""
    chunk_is_error = in_error_event
    next_state = in_error_event

    for line in chunk.splitlines():
        if line.startswith("event:"):
            next_state = line.removeprefix("event:").strip() == "error"
            chunk_is_error = chunk_is_error or next_state
            continue
        if line.startswith("data:"):
            try:
                payload = json.loads(line.removeprefix("data:").strip())
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("type") == "error":
                next_state = True
                chunk_is_error = True
            continue
        if not line:
            next_state = False

    return chunk_is_error, next_state


def _extract_usage_from_sse_line(line: str) -> dict[str, int] | None:
    """Parse usage from message_start / message_delta data lines in the SSE stream.

    message_start carries input/cache_read/cache_creation (per-request totals).
    message_delta carries cumulative output_tokens; some reverse-engineered
    Anthropic upstreams (e.g. api.minimaxi.com/anthropic) also re-emit
    input_tokens in deltas — those are the authoritative non-zero values when
    message_start reported 0. The caller (billing_stream) uses last-wins
    assignment with a truthy guard, so both events cooperate cleanly.
    """
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
            # Some reverse-engineered Anthropic upstreams (e.g. api.minimaxi.com)
            # also re-emit input_tokens in delta events; capture it so the
            # non-zero value isn't lost when message_start reports 0.
            result["input_tokens"] = usage.get("input_tokens", 0)
            # DeepSeek provider normalizer may inject cache fields into delta events
            result["cache_read_tokens"] = usage.get("cache_read_input_tokens", 0)
            result["cache_creation_tokens"] = usage.get("cache_creation_input_tokens", 0)

    return result


def _extract_message_id_from_sse_line(line: str) -> str | None:
    """Extract the upstream ``message.id`` from a message_start data line.

    Anthropic's message_start event carries the unique message identifier
    (e.g. ``msg_01ABCxyz...``) under ``message.id``. Only message_start
    carries it — message_delta, content_block_*, and message_stop do not.

    Returns ``None`` for non-data lines, malformed JSON, non-message_start
    events, and payloads missing the ``message.id`` field.
    """
    if not line.startswith("data:"):
        return None
    try:
        payload = json.loads(line.removeprefix("data:").strip())
    except json.JSONDecodeError:
        return None
    if payload.get("type") != "message_start":
        return None
    msg = payload.get("message")
    if not isinstance(msg, dict):
        return None
    msg_id = msg.get("id")
    return msg_id if isinstance(msg_id, str) and msg_id else None


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
                ChannelKey.provider_id == channel_id,
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
    selected_key = keys[0]
    try:
        return decrypt_api_key(selected_key.key_encrypted, provider_id=provider_id)
    except InvalidTag as exc:
        logger.error(
            "Failed to decrypt provider key id=%s for provider_id=%s",
            selected_key.id,
            provider_id,
        )
        raise AppException(
            status_code=500,
            error="上游服务配置错误",
            code="UPSTREAM_CONFIG_ERROR",
        ) from exc


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
    if api_key.channel_id is not None:
        routed = await router_.resolve_with_channel(body.model, api_key.channel_id)
    else:
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

    # ── 2a. Resolve token coefficient (discount) for this model ─
    tcs = getattr(request.app.state, "token_coefficient_service", None)
    if tcs is not None:
        coefficient = tcs.get_for_model(model.id)
    else:
        coefficient = 1.0

    # ── 3. Get provider ───────────────────────────────────────
    provider_result = await db.execute(select(Provider).where(Provider.id == routed.db_provider_id))
    provider = provider_result.scalar_one_or_none()
    if not provider or provider.status != "active":
        raise AppException(status_code=500, error="上游提供商不可用", code="PROVIDER_UNAVAILABLE")

    # ── 4. Get upstream API key from key pool ─────────────────
    upstream_api_key = await _get_active_upstream_key(db, provider.id, channel_id=provider.id)
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
    provider_body = body.model_copy(
        update={
            "model": routed.provider_model,
            # 把用户最初请求的 Claude 模型名带给 provider，让 SSE message_start
            # 中上游回写的模型名（如讯飞的 astron-code-latest）能被改写回原始名。
            "original_model": body.model,
            "resolved_provider_model": routed.provider_model,
        },
        deep=True,
    )

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

    provider_stream = provider_instance.stream_response(
        provider_body,
        request_id=f"req_{body.model}",
    )
    first_chunk: str | None = None

    async def provider_chunks():
        if first_chunk is not None:
            yield first_chunk
        async for chunk in provider_stream:
            yield chunk

    async def billing_stream():
        nonlocal accumulated_usage
        # Captured from message_start — the upstream Anthropic message.id
        # (e.g. "msg_01ABCxyz..."). Persisted so the call record can be
        # cross-referenced with Claude Code JSONL session files and the
        # upstream provider's logs. message_start fires exactly once per
        # response, so last-wins assignment is correct.
        upstream_message_id: str | None = None
        stream_completed = False
        saw_upstream_error = False
        in_error_event = False
        try:
            trace_event(
                stage="egress",
                event="proxy.stream.start",
                source="api",
                provider_id=routed.provider_id,
                gateway_model=body.model,
                provider_model=routed.provider_model,
            )
            async for chunk in provider_chunks():
                error_chunk, in_error_event = _sse_error_chunk_state(chunk, in_error_event)
                saw_upstream_error = saw_upstream_error or error_chunk
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
                # Capture the upstream message.id from the message_start event.
                mid = _extract_message_id_from_sse_line(chunk)
                if mid:
                    upstream_message_id = mid
                if not error_chunk:
                    if _remap_model:
                        chunk = chunk.replace(_provider_model, _original_model)
                    chunk = _apply_coefficient_to_sse_event(chunk, coefficient)
                yield chunk
            stream_completed = True
        finally:
            close_provider_stream = getattr(provider_stream, "aclose", None)
            if callable(close_provider_stream):
                try:
                    await close_provider_stream()
                except Exception:
                    logger.exception(
                        "Failed to close provider stream for user=%d model=%s",
                        user_id,
                        body.model,
                    )
            has_reported_usage = any(accumulated_usage.values())
            should_bill = (stream_completed and not saw_upstream_error) or has_reported_usage
            if should_bill:
                adjusted = apply_coefficient(
                    input_tokens=accumulated_usage["input_tokens"] or 0,
                    cache_read_tokens=accumulated_usage["cache_read_tokens"] or 0,
                    cache_creation_tokens=accumulated_usage["cache_creation_tokens"] or 0,
                    output_tokens=accumulated_usage["output_tokens"] or 0,
                    coefficient=coefficient,
                )
                try:
                    from app.services.billing.pending import write_pending_billing

                    await write_pending_billing(
                        db,
                        request_id=uuid.uuid4(),
                        user_id=user_id,
                        api_key_id=api_key_id,
                        model_id=model.id,
                        route_id=routed.db_route_id,
                        provider_id=provider.id,
                        input_tokens=adjusted.input_tokens,
                        output_tokens=adjusted.output_tokens,
                        cache_read_tokens=adjusted.cache_read_tokens,
                        cache_creation_tokens=adjusted.cache_creation_tokens,
                        upstream_message_id=upstream_message_id,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "Failed to write pending_billing for user=%d model=%s",
                        user_id,
                        body.model,
                    )

    # Release the request-scoped transaction before the long-lived stream starts;
    # the finally block in billing_stream will start a fresh transaction for the
    # pending_billing write.
    await db.commit()

    # Open the upstream stream before committing downstream HTTP 200. This is the
    # only point where an upstream HTTP error can still retain its original status.
    try:
        first_chunk = await anext(provider_stream)
    except StopAsyncIteration:
        first_chunk = None
    except UpstreamResponseError as exc:
        trace_event(
            stage="egress",
            event="proxy.upstream_error.passthrough",
            source="api",
            provider_id=routed.provider_id,
            gateway_model=body.model,
            status_code=exc.status_code,
        )
        if exc.status_code in {401, 403}:
            raise APIError(
                "Gateway upstream provider authentication failed.", status_code=502
            ) from exc
        return Response(
            content=exc.body,
            status_code=exc.status_code,
            headers=_passthrough_upstream_headers(exc.headers),
        )
    except (httpx.ReadTimeout, TimeoutError) as exc:
        raise APIError(
            "Gateway timed out waiting for the upstream provider.", status_code=504
        ) from exc
    except httpx.TransportError as exc:
        raise APIError(
            "Gateway could not connect to the upstream provider.", status_code=502
        ) from exc

    return StreamingResponse(
        billing_stream(),
        media_type="text/event-stream",
        headers=ANTHROPIC_SSE_RESPONSE_HEADERS,
    )

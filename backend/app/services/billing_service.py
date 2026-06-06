"""Billing service — token recording, cost computation, and settlement (Epic 3).

Story 3-1: After every API request, extract token counts from the upstream
response.usage field, compute the cost using model pricing × channel multiplier,
and write an append-only RequestLog entry.

Story 3-2: BillingRecord is created synchronously within each API request,
recording the post-deduction balance as the audit ledger entry.

Cost formula (per Story 3.1 AC):
    cost = input × input_price + output × output_price × channel.multiplier

Prices are stored in micro-yuan per 1K tokens; cost is returned in cents (分).
"""

import logging
import math
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_record import BillingRecord
from app.models.model import ChannelConfig, Model
from app.models.request_log import RequestLog

logger = logging.getLogger("high-api.billing")

# ── Token extraction ──────────────────────────────────────────────


def extract_usage(upstream_response_body: dict) -> tuple[int, int, int, bool]:
    """Extract (input_tokens, output_tokens, cache_read_tokens, is_valid) from upstream response.

    Supports both Anthropic (usage.input_tokens / usage.output_tokens /
    usage.cache_read_input_tokens) and OpenAI (usage.prompt_tokens /
    usage.completion_tokens) formats.

    Returns:
        (input_tokens, output_tokens, cache_read_tokens, is_valid)
        is_valid is False when the usage field is missing or malformed.
    """
    try:
        usage = upstream_response_body.get("usage")
        if not isinstance(usage, dict):
            return 0, 0, 0, False

        # Anthropic format (preferred)
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)

        # Also support OpenAI format (prompt_tokens/completion_tokens)
        # Fall back only when Anthropic fields are absent
        if input_tokens is None:
            input_tokens = usage.get("prompt_tokens", 0)
        if output_tokens is None:
            output_tokens = usage.get("completion_tokens", 0)

        # Both must be non-negative integers
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return 0, 0, 0, False
        if input_tokens < 0 or output_tokens < 0:
            return 0, 0, 0, False

        # At least one token should have been consumed
        if input_tokens == 0 and output_tokens == 0:
            return 0, 0, 0, False

        # Ensure cache_read_tokens is a non-negative int
        if not isinstance(cache_read_tokens, int) or cache_read_tokens < 0:
            cache_read_tokens = 0

        return input_tokens, output_tokens, cache_read_tokens, True

    except (KeyError, TypeError, AttributeError):
        return 0, 0, 0, False


# ── Cost computation ───────────────────────────────────────────────


def compute_cost(
    input_tokens: int,
    output_tokens: int,
    input_price_micro_yuan: int,
    output_price_micro_yuan: int,
    channel_multiplier: float = 1.0,
    cache_read_tokens: int = 0,
    cache_read_price_micro_yuan: int = 0,
) -> int:
    """Compute request cost in cents (分), rounding up.

    Three-segment pricing:
      cost = (input_tokens × input_price
            + output_tokens × output_price
            + cache_read_tokens × cache_read_price) × channel_multiplier

    All prices are in micro yuan per 1K tokens. Result is in cents.
    """
    # Prices are in micro yuan per 1K tokens
    input_cost_uy = (input_tokens / 1000.0) * input_price_micro_yuan
    output_cost_uy = (output_tokens / 1000.0) * output_price_micro_yuan
    cache_read_cost_uy = (cache_read_tokens / 1000.0) * cache_read_price_micro_yuan

    total_micro_yuan = (input_cost_uy + output_cost_uy + cache_read_cost_uy) * channel_multiplier
    cost_cents = math.ceil(total_micro_yuan / 10_000)
    return max(0, cost_cents)


# ── Database operations ────────────────────────────────────────────


async def record_request_log(
    db: AsyncSession,
    *,
    user_id: int,
    sk_id: int,
    model_id: int,
    channel_id: int,
    provider_id: int,
    input_tokens: int,
    output_tokens: int,
    cost_cents: int,
    latency_ms: int | None = None,
    status: str = "success",
) -> RequestLog:
    """Create an append-only RequestLog entry.

    Called within the same request lifecycle as the API proxy.
    The caller is responsible for committing the transaction.
    """
    request_log = RequestLog(
        request_id=uuid.uuid4().hex,
        user_id=user_id,
        sk_id=sk_id,
        model_id=model_id,
        channel_id=channel_id,
        provider_id=provider_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
        latency_ms=latency_ms,
        status=status,
    )
    db.add(request_log)
    return request_log


async def resolve_channel_for_model(
    db: AsyncSession,
    model_id: int,
    provider_id: int,
) -> ChannelConfig | None:
    """Find the active channel config for a model+provider pair.

    Prefers the default channel; falls back to the first active channel.
    """
    result = await db.execute(
        select(ChannelConfig)
        .where(
            ChannelConfig.model_id == model_id,
            ChannelConfig.provider_id == provider_id,
            ChannelConfig.status == "active",
            ChannelConfig.multiplier > 0,
        )
        .order_by(ChannelConfig.is_default.desc())  # default first
    )
    return result.scalars().first()


async def process_token_recording(
    db: AsyncSession,
    *,
    user_id: int,
    sk_id: int,
    model_id: int,
    channel_config: ChannelConfig,
    upstream_response_body: dict,
    latency_ms: int | None = None,
    balance_after_cents: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cost_cents: int | None = None,
) -> RequestLog:
    """Extract tokens from upstream response, compute cost, and record RequestLog.

    This is the main entry point for Story 3-1. It encapsulates the full
    token-recording lifecycle within the proxy request handler.

    Args:
        db: Active database session.
        user_id: Authenticated user.
        sk_id: The API key used.
        model_id: Database ID of the requested model.
        channel_config: Resolved channel config (with multiplier).
        upstream_response_body: Full JSON response body from upstream AI provider.
        latency_ms: Measured end-to-end latency (optional).
        input_tokens: Pre-extracted input token count (skips re-extraction if provided).
        output_tokens: Pre-extracted output token count.
        cache_read_tokens: Pre-extracted cache read token count.
        cost_cents: Pre-computed cost in cents (skips re-computation if provided).

    Returns:
        The created RequestLog entry (not yet committed — caller owns the txn).
    """
    # 1. Extract tokens from upstream usage (or use caller-provided values)
    if input_tokens is not None and output_tokens is not None:
        usage_valid = not (input_tokens == 0 and output_tokens == 0)
        _input = input_tokens
        _output = output_tokens
        _cache_read = cache_read_tokens or 0
    else:
        _input, _output, _cache_read, usage_valid = extract_usage(upstream_response_body)

    if not usage_valid:
        logger.warning(
            "Usage missing or invalid in upstream response. request_model_id=%d user_id=%d",
            model_id,
            user_id,
        )
        return await record_request_log(
            db=db,
            user_id=user_id,
            sk_id=sk_id,
            model_id=model_id,
            channel_id=channel_config.id,
            provider_id=channel_config.provider_id,
            input_tokens=0,
            output_tokens=0,
            cost_cents=0,
            latency_ms=latency_ms,
            status="usage_missing",
        )

    # 2. Compute cost (or use caller-provided value)
    if cost_cents is None:
        # Look up model pricing
        model_result = await db.execute(
            select(Model.input_price, Model.output_price, Model.cache_read_price).where(
                Model.id == model_id
            )
        )
        model_row = model_result.one_or_none()
        if not model_row:
            logger.error("Model %d not found during token recording", model_id)
            return await record_request_log(
                db=db,
                user_id=user_id,
                sk_id=sk_id,
                model_id=model_id,
                channel_id=channel_config.id,
                provider_id=channel_config.provider_id,
                input_tokens=_input,
                output_tokens=_output,
                cost_cents=0,
                latency_ms=latency_ms,
                status="error",
            )

        # Compute cost with channel multiplier
        input_price, output_price, cache_read_price = (
            model_row.input_price,
            model_row.output_price,
            model_row.cache_read_price,
        )
        cost_cents = compute_cost(
            input_tokens=_input,
            output_tokens=_output,
            input_price_micro_yuan=input_price,
            output_price_micro_yuan=output_price,
            channel_multiplier=channel_config.multiplier,
            cache_read_tokens=_cache_read,
            cache_read_price_micro_yuan=cache_read_price,
        )

    # 4. Record RequestLog
    request_log = await record_request_log(
        db=db,
        user_id=user_id,
        sk_id=sk_id,
        model_id=model_id,
        channel_id=channel_config.id,
        provider_id=channel_config.provider_id,
        input_tokens=_input,
        output_tokens=_output,
        cost_cents=cost_cents,
        latency_ms=latency_ms,
        status="success",
    )

    # 5. Flush to get the request_log.id assigned by the DB, then
    #    create the matching BillingRecord synchronously (Story 3-2).
    #    Balance is already deducted by the caller — we record the
    #    post-deduction balance here as the audit ledger entry.
    await db.flush()

    if cost_cents > 0:
        db.add(
            BillingRecord(
                user_id=user_id,
                request_log_id=request_log.id,
                amount_cents=cost_cents,
                balance_after_cents=balance_after_cents,
            )
        )

    return request_log


# ── Settlement (Story 3-2) — removed ───────────────────────────────
# BillingRecord creation moved into process_token_recording (above).
# The background scheduler has been removed — billing is now
# synchronous with each API request.

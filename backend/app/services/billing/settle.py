"""Settle one pending_billing row — deduct balance and write three audit tables."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_record import BillingRecord
from app.models.model import Model
from app.models.pending_billing import PendingBilling
from app.models.request_log import RequestLog
from app.models.usage import UsageRecord
from app.models.user import User
from app.services.billing.compute import compute_costs_for_pending

logger = logging.getLogger("cloude-gateway.billing.settle")


async def settle_one(db: AsyncSession, pending: PendingBilling) -> None:
    """Settle a single pending_billing row.

    Caller owns the transaction: success path commits, failure path rolls back.
    On any exception, the caller is expected to roll back AND increment
    retry_count on the pending row in a follow-up transaction.
    """
    cost = await compute_costs_for_pending(pending, db)
    model = await db.scalar(select(Model).where(Model.id == pending.model_id))

    # Lock user row
    user = await db.scalar(
        select(User).where(User.id == pending.user_id).with_for_update()
    )
    if user is None:
        raise RuntimeError(f"User {pending.user_id} not found")
    user.balance = user.balance - cost
    balance_after = user.balance

    # Write request_log
    rl = RequestLog(
        request_id=pending.request_id.hex,
        user_id=pending.user_id,
        sk_id=pending.api_key_id,
        model_id=pending.model_id,
        channel_id=pending.channel_id,
        provider_id=pending.provider_id,
        input_tokens=pending.input_tokens,
        output_tokens=pending.output_tokens,
        cost_cents=cost,
        status="success",
    )
    db.add(rl)
    await db.flush()  # need rl.id for BillingRecord FK

    # Write billing_record (1:1 with request_log)
    db.add(
        BillingRecord(
            user_id=pending.user_id,
            request_log_id=rl.id,
            amount_cents=cost,
            balance_after_cents=balance_after,
        )
    )

    # Write usage_record
    db.add(
        UsageRecord(
            user_id=pending.user_id,
            api_key_id=pending.api_key_id,
            model=model.public_name,
            input_tokens=pending.input_tokens,
            output_tokens=pending.output_tokens,
            cache_read_tokens=pending.cache_read_tokens,
            cache_creation_tokens=pending.cache_creation_tokens,
            cost_cents=cost,
            channel_id=pending.channel_id,
        )
    )

    # Mark pending settled
    pending.status = "settled"
    pending.settled_at = datetime.now(timezone.utc)


async def mark_retry(db: AsyncSession, pending: PendingBilling, exc: Exception) -> None:
    """Increment retry_count and record last_error. Caller commits."""
    pending.retry_count += 1
    pending.last_error = f"{type(exc).__name__}: {exc}"[:2000]


def max_retry_reached(pending: PendingBilling, max_retry: int = 3) -> bool:
    return pending.retry_count > max_retry

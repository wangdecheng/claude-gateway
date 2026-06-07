"""Pending billing queue — write from proxy, claim from worker."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_billing import PendingBilling


async def write_pending_billing(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    user_id: int,
    api_key_id: int,
    model_id: int,
    channel_id: int,
    provider_id: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> PendingBilling:
    """Insert a pending_billing row. Caller owns the transaction.

    The ``request_id`` is UNIQUE — duplicate writes raise IntegrityError.
    """
    pb = PendingBilling(
        request_id=request_id,
        user_id=user_id,
        api_key_id=api_key_id,
        model_id=model_id,
        channel_id=channel_id,
        provider_id=provider_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        status="pending",
        retry_count=0,
    )
    db.add(pb)
    await db.flush()
    return pb

"""RequestLog model — append-only audit trail for every API request.

Each POST /v1/messages (or equivalent) creates one RequestLog row capturing:
  - Who made the request (user_id, sk_id)
  - What was requested (model_id, channel_id, provider_id)
  - How many tokens were consumed (input_tokens, output_tokens)
  - How much it cost (cost_cents, computed with channel multiplier)
  - Whether the upstream response included valid usage data (status)

This is the source of truth for the billing engine (Epic 3).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity — unique per request for cross-system correlation
    request_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: uuid.uuid4().hex,
        comment="UUID v4 — stable identifier for this request across logs and billing",
    )

    # Who
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    sk_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("api_keys.id"), nullable=False, index=True
    )

    # What — denormalised for query performance (avoids joins on hot path)
    model_id: Mapped[int] = mapped_column(Integer, ForeignKey("models.id"), nullable=False)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channel_configs.id"), nullable=False
    )
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False)

    # Tokens — extracted from upstream response.usage
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Prompt tokens from upstream usage"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Completion tokens from upstream usage"
    )

    # Cost — computed as (input × input_price + output × output_price × channel.multiplier)
    # Stored in cents (分). Always ≥ 0.
    cost_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Cost in cents (分)"
    )

    # Latency
    latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="End-to-end latency in milliseconds"
    )

    # Status
    #   success        — upstream returned valid usage
    #   usage_missing  — upstream response lacked usage field or it was malformed
    #   error          — upstream returned an error (connection, timeout, 5xx, etc.)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success", comment="success | usage_missing | error"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

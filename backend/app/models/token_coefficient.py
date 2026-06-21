"""Token coefficient (discount) config — global default + per-model override.

A single coefficient in (0, 1] is applied to three of the four Anthropic token
fields — input / cache_creation / output. The fourth field, ``cache_read_input_tokens``,
is NOT discounted; it is passed through at the raw upstream value. See
:mod:`app.services.billing.token_coefficient` and the 2026-06-21 delta spec for
the rationale (upstream providers already discount cache reads heavily).

The coefficient is applied to the API response (SSE usage fields) and to the
PendingBilling write (so downstream RequestLog / BillingRecord / UsageRecord
all see the adjusted values).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TokenCoefficientConfig(Base):
    __tablename__ = "token_coefficient_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    model_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=True
    )
    coefficient: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("model_id", name="uq_token_coefficient_configs_model_id"),
        CheckConstraint(
            "coefficient > 0 AND coefficient <= 1",
            name="ck_token_coefficient_configs_range",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND model_id IS NULL) OR "
            "(scope_type = 'model' AND model_id IS NOT NULL)",
            name="ck_token_coefficient_configs_scope_model",
        ),
    )

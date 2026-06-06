"""BillingRecord model — append-only deduction ledger (Epic 3 Story 3-2).

Each row records one settled charge: which RequestLog was charged, how much,
and what the user's balance became after the deduction.

Constraints:
  - request_log_id is UNIQUE — a RequestLog can only be charged once.
  - Append-only: application code never issues UPDATE/DELETE against this table.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BillingRecord(Base):
    __tablename__ = "billing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    # One-to-one with RequestLog — the UNIQUE constraint prevents double-charging.
    request_log_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("request_logs.id"),
        unique=True,
        nullable=False,
        comment="FK to request_logs; UNIQUE ensures each request is charged at most once",
    )

    # Amount deducted in this settlement, in cents (分). Always ≥ 0.
    amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Deducted amount in cents (分)"
    )

    # User's balance AFTER this deduction. Captured for audit trail.
    balance_after_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="User balance after deduction, in cents"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

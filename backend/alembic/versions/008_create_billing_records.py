"""create billing_records table

Revision ID: 008
Revises: 007
Create Date: 2026-05-31

Epic 3 Story 3-2: Append-only deduction ledger.
Each row pairs one RequestLog with its settled charge amount and
the user's balance after deduction. The UNIQUE constraint on
request_log_id prevents double-charging.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "request_log_id",
            sa.Integer(),
            sa.ForeignKey("request_logs.id"),
            unique=True,
            nullable=False,
            comment="FK to request_logs; UNIQUE ensures each request is charged at most once",
        ),
        sa.Column(
            "amount_cents",
            sa.Integer(),
            nullable=False,
            comment="Deducted amount in cents (分)",
        ),
        sa.Column(
            "balance_after_cents",
            sa.Integer(),
            nullable=False,
            comment="User balance after deduction, in cents",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_billing_records_user_id", "billing_records", ["user_id"])
    op.create_index("idx_billing_records_created_at", "billing_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_billing_records_created_at", table_name="billing_records")
    op.drop_index("idx_billing_records_user_id", table_name="billing_records")
    op.drop_table("billing_records")

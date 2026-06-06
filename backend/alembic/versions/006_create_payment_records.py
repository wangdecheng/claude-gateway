"""create payment_records table

Revision ID: 006
Revises: 005 (create_redemption_codes)
Create Date: 2026-05-31
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("transaction_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_payment_records_transaction_id"),
        sa.CheckConstraint("amount > 0", name="ck_payment_records_amount_positive"),
    )
    op.create_index(
        "idx_payment_records_user",
        "payment_records",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_payment_records_transaction",
        "payment_records",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_table("payment_records")

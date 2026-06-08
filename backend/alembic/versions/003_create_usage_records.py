"""create usage_records table

Revision ID: 003
Revises: 002
Create Date: 2026-05-31
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_usage_user_id", "usage_records", ["user_id"])
    op.create_index("idx_usage_api_key_id", "usage_records", ["api_key_id"])
    op.create_index("idx_usage_created_at", "usage_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_usage_created_at", table_name="usage_records")
    op.drop_index("idx_usage_api_key_id", table_name="usage_records")
    op.drop_index("idx_usage_user_id", table_name="usage_records")
    op.drop_table("usage_records")

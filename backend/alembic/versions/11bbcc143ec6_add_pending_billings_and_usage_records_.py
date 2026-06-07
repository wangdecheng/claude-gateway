"""add pending_billings and usage_records.channel_id

Revision ID: 11bbcc143ec6
Revises: c08f886da667
Create Date: 2026-06-07 11:01:00.924508
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "11bbcc143ec6"
down_revision: Union[str, None] = "c08f886da667"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pending_billings table
    op.create_table(
        "pending_billings",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("request_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channel_configs.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
    )
    op.create_index(
        "ix_pending_billings_request_id",
        "pending_billings",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        "ix_pending_billings_pending",
        "pending_billings",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # usage_records.channel_id
    op.add_column("usage_records", sa.Column("channel_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_usage_records_channel_id",
        "usage_records",
        "channel_configs",
        ["channel_id"],
        ["id"],
    )
    op.create_index("ix_usage_records_channel_id", "usage_records", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_channel_id", table_name="usage_records")
    op.drop_constraint("fk_usage_records_channel_id", "usage_records", type_="foreignkey")
    op.drop_column("usage_records", "channel_id")
    op.drop_index("ix_pending_billings_pending", table_name="pending_billings")
    op.drop_index("ix_pending_billings_request_id", table_name="pending_billings")
    op.drop_table("pending_billings")

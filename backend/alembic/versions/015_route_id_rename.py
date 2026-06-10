"""rename channel_id -> route_id on billing tables (request_logs, pending_billings, usage_records)

Revision ID: 015
Revises: 014
Create Date: 2026-06-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # request_logs
    with op.batch_alter_table("request_logs") as batch:
        # 013 DROPped channel_configs CASCADE, taking request_logs_channel_id_fkey
        # with it, so the constraint no longer exists when 015 runs. Use
        # IF EXISTS so the DDL is idempotent across the CASCADE path.
        op.execute("ALTER TABLE request_logs DROP CONSTRAINT IF EXISTS request_logs_channel_id_fkey")
        batch.alter_column(
            "channel_id",
            new_column_name="route_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch.create_foreign_key(
            "request_logs_route_id_fkey",
            "model_providers",
            ["route_id"],
            ["id"],
        )

    # pending_billings
    with op.batch_alter_table("pending_billings") as batch:
        op.execute("ALTER TABLE pending_billings DROP CONSTRAINT IF EXISTS pending_billings_channel_id_fkey")
        batch.alter_column(
            "channel_id",
            new_column_name="route_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch.create_foreign_key(
            "pending_billings_route_id_fkey",
            "model_providers",
            ["route_id"],
            ["id"],
        )

    # usage_records
    with op.batch_alter_table("usage_records") as batch:
        op.execute("ALTER TABLE usage_records DROP CONSTRAINT IF EXISTS usage_records_channel_id_fkey")
        batch.alter_column(
            "channel_id",
            new_column_name="route_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch.create_foreign_key(
            "usage_records_route_id_fkey",
            "model_providers",
            ["route_id"],
            ["id"],
        )
        batch.drop_index("ix_usage_records_channel_id")
        batch.create_index("ix_usage_records_route_id", ["route_id"])


def downgrade() -> None:
    with op.batch_alter_table("usage_records") as batch:
        batch.drop_index("ix_usage_records_route_id")
        batch.alter_column(
            "route_id",
            new_column_name="channel_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch.create_index("ix_usage_records_channel_id", ["channel_id"])

    with op.batch_alter_table("pending_billings") as batch:
        batch.alter_column(
            "route_id",
            new_column_name="channel_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    with op.batch_alter_table("request_logs") as batch:
        batch.alter_column(
            "route_id",
            new_column_name="channel_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

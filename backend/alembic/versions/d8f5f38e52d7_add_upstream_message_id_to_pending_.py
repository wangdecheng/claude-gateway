"""add upstream_message_id to pending_billings and request_logs

Revision ID: d8f5f38e52d7
Revises: 11bbcc143ec6
Create Date: 2026-06-07 16:34:16.443537
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "d8f5f38e52d7"
down_revision: Union[str, None] = "11bbcc143ec6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Persist the upstream Anthropic message.id (from message_start SSE event,
    # e.g. "msg_01ABCxyz...") so call records can be cross-referenced with
    # Claude Code JSONL session files and the upstream provider's logs.
    op.add_column(
        "pending_billings",
        sa.Column("upstream_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_pending_billings_upstream_message_id"),
        "pending_billings",
        ["upstream_message_id"],
        unique=False,
    )
    op.add_column(
        "request_logs",
        sa.Column("upstream_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_request_logs_upstream_message_id"),
        "request_logs",
        ["upstream_message_id"],
        unique=False,
    )
    op.add_column(
        "usage_records",
        sa.Column("upstream_message_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_usage_records_upstream_message_id"),
        "usage_records",
        ["upstream_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_usage_records_upstream_message_id"), table_name="usage_records"
    )
    op.drop_column("usage_records", "upstream_message_id")
    op.drop_index(
        op.f("ix_request_logs_upstream_message_id"), table_name="request_logs"
    )
    op.drop_column("request_logs", "upstream_message_id")
    op.drop_index(
        op.f("ix_pending_billings_upstream_message_id"),
        table_name="pending_billings",
    )
    op.drop_column("pending_billings", "upstream_message_id")

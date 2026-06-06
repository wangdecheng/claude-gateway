"""create request_logs table

Revision ID: 007
Revises: 006
Create Date: 2026-05-31

Epic 3 Story 3-1: Append-only audit trail for every API request.
Each POST /v1/messages creates one row capturing user, sk, model, channel,
provider, token counts, cost, and status.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "request_id",
            sa.String(36),
            unique=True,
            nullable=False,
            comment="UUID v4 — stable identifier for this request across logs and billing",
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sk_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channel_configs.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Prompt tokens from upstream usage",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Completion tokens from upstream usage",
        ),
        sa.Column(
            "cost_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Cost in cents (分)",
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=True,
            comment="End-to-end latency in milliseconds",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="success",
            comment="success | usage_missing | error",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Indexes for common query patterns
    op.create_index("idx_request_logs_user_id", "request_logs", ["user_id"])
    op.create_index("idx_request_logs_sk_id", "request_logs", ["sk_id"])
    op.create_index("idx_request_logs_model_id", "request_logs", ["model_id"])
    op.create_index("idx_request_logs_provider_id", "request_logs", ["provider_id"])
    op.create_index("idx_request_logs_created_at", "request_logs", ["created_at"])
    op.create_index("idx_request_logs_status", "request_logs", ["status"])


def downgrade() -> None:
    op.drop_index("idx_request_logs_status", table_name="request_logs")
    op.drop_index("idx_request_logs_created_at", table_name="request_logs")
    op.drop_index("idx_request_logs_provider_id", table_name="request_logs")
    op.drop_index("idx_request_logs_model_id", table_name="request_logs")
    op.drop_index("idx_request_logs_sk_id", table_name="request_logs")
    op.drop_index("idx_request_logs_user_id", table_name="request_logs")
    op.drop_table("request_logs")

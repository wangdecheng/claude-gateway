"""create providers, models, channel_configs tables

Revision ID: 004
Revises: 003
Create Date: 2026-05-31
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- providers ---
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("api_base_url", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("idx_providers_status", "providers", ["status"])

    # --- models ---
    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_name", sa.String(100), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("provider_model_id", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Prices are stored as micro-yuan per 1K tokens to preserve values like ¥0.015.
        sa.Column("input_price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_price", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("input_price >= 0", name="ck_models_input_price_non_negative"),
        sa.CheckConstraint("output_price >= 0", name="ck_models_output_price_non_negative"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_name"),
    )
    op.create_index("idx_models_status", "models", ["status"])
    op.create_index("idx_models_provider_id", "models", ["provider_id"])

    # --- channel_configs ---
    op.create_table(
        "channel_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("multiplier", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("multiplier > 0", name="ck_channel_configs_multiplier_positive"),
    )
    op.create_index("idx_channel_configs_status", "channel_configs", ["status"])
    op.create_index("idx_channel_configs_model_id", "channel_configs", ["model_id"])
    op.create_index("idx_channel_configs_provider_id", "channel_configs", ["provider_id"])
    # Enforce at most one default channel per model
    op.execute(
        "CREATE UNIQUE INDEX idx_one_default_per_model "
        "ON channel_configs (model_id) WHERE is_default = true;"
    )


def downgrade() -> None:
    op.drop_index("idx_one_default_per_model", table_name="channel_configs")
    op.drop_index("idx_channel_configs_provider_id", table_name="channel_configs")
    op.drop_index("idx_channel_configs_model_id", table_name="channel_configs")
    op.drop_index("idx_channel_configs_status", table_name="channel_configs")
    op.drop_table("channel_configs")
    op.drop_index("idx_models_provider_id", table_name="models")
    op.drop_index("idx_models_status", table_name="models")
    op.drop_table("models")
    op.drop_index("idx_providers_status", table_name="providers")
    op.drop_table("providers")

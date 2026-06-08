"""channel binding: providers.channel_name, api_keys.channel_id, model_providers, channel_keys rename

Revision ID: 010
Revises: 009
Create Date: 2026-06-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "12b1c4d7ae30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. providers.channel_name + multiplier
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("channel_name", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column(
                "multiplier",
                sa.Float(),
                nullable=False,
                server_default="1.0",
                comment="Pricing multiplier applied when billing through this provider",
            )
        )
    # Backfill channel_name from existing data
    op.execute("UPDATE providers SET channel_name = name WHERE channel_name IS NULL")
    with op.batch_alter_table("providers") as batch:
        batch.alter_column("channel_name", nullable=False)
    # Drop the old unique constraint on name (we now have composite unique)
    try:
        op.drop_constraint("uq_providers_name", "providers", type_="unique")
    except Exception:
        pass  # may not exist on some DBs
    op.create_unique_constraint(
        "uq_providers_name_channel_name", "providers", ["name", "channel_name"]
    )

    # 2. New model_providers table
    op.create_table(
        "model_providers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("provider_model", sa.String(200), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("model_id", "provider_id", name="uq_model_provider"),
    )

    # 3. channel_keys.channel_id -> provider_id
    with op.batch_alter_table("channel_keys") as batch:
        # Drop old FK and unique constraint
        try:
            batch.drop_constraint("channel_keys_channel_id_fkey", type_="foreignkey")
        except Exception:
            pass
        try:
            batch.drop_constraint("uq_channel_provider_key", type_="unique")
        except Exception:
            pass
        # Rename column
        batch.alter_column(
            "channel_id",
            new_column_name="provider_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        # Add new FK and unique
        batch.create_foreign_key(
            "channel_keys_provider_id_fkey",
            "providers",
            ["provider_id"],
            ["id"],
        )
        batch.create_unique_constraint("uq_provider_key", ["provider_id", "provider_key_id"])

    # 4. api_keys.channel_id
    op.add_column(
        "api_keys",
        sa.Column(
            "channel_id",
            sa.Integer(),
            nullable=True,
            comment="Bound provider; NULL = legacy auto behavior",
        ),
    )
    op.create_index("ix_api_keys_channel_id", "api_keys", ["channel_id"])
    op.create_foreign_key(
        "api_keys_channel_id_fkey",
        "api_keys",
        "providers",
        ["channel_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5. Drop channel_configs (data migration must have run first).
    op.drop_table("channel_configs")


def downgrade() -> None:
    # Best-effort reverse; not used in production (system pre-launch).
    op.create_table(
        "channel_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("models.id")),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id")),
        sa.Column("provider_model_id", sa.String(200)),
        sa.Column("name", sa.String(50)),
        sa.Column("multiplier", sa.Float()),
        sa.Column("status", sa.String(20)),
        sa.Column("is_default", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.drop_table("model_providers")
    with op.batch_alter_table("channel_keys") as batch:
        batch.alter_column(
            "provider_id",
            new_column_name="channel_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    op.drop_column("api_keys", "channel_id")
    with op.batch_alter_table("providers") as batch:
        batch.drop_constraint("uq_providers_name_channel_name", type_="unique")
        batch.drop_column("multiplier")
        batch.drop_column("channel_name")

"""add_channel_keys_table

Revision ID: a1b5b82a1351
Revises: 2478a3d0f8ca
Create Date: 2026-06-05 22:51:14.575562
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "a1b5b82a1351"
down_revision: Union[str, None] = "2478a3d0f8ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("provider_key_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel_configs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["provider_key_id"],
            ["provider_keys.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", "provider_key_id", name="uq_channel_provider_key"),
    )


def downgrade() -> None:
    op.drop_table("channel_keys")

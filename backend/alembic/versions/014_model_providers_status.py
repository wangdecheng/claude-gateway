"""add status column to model_providers

Revision ID: 014
Revises: 013
Create Date: 2026-06-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("model_providers") as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="active",
                comment="active | inactive | deleted (soft-delete, preserves billing history)",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("model_providers") as batch:
        batch.drop_column("status")

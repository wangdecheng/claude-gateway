"""add_cache_read_price_to_models

Revision ID: 2478a3d0f8ca
Revises: 010
Create Date: 2026-06-05 22:49:12.795343
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "2478a3d0f8ca"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column(
            "cache_read_price",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Cache read price in micro yuan per 1K tokens",
        ),
    )


def downgrade() -> None:
    op.drop_column("models", "cache_read_price")

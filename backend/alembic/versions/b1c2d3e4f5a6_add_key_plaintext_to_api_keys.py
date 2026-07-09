"""add key_plaintext to api_keys

Revision ID: b1c2d3e4f5a6
Revises: dc16e024a564
Create Date: 2026-07-09 10:00:00.000000

Adds a nullable key_plaintext column to api_keys so the user-facing sk
can be surfaced in the UI for multi-copy. Authentication continues to
use the bcrypt-hashed key_hash column.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "dc16e024a564"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("key_plaintext", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "key_plaintext")

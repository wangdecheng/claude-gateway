"""widen provider_keys.key_prefix to varchar(20)

Revision ID: 12b1c4d7ae30
Revises: d8f5f38e52d7
Create Date: 2026-06-07 19:30:00.000000

Migration 010_create_provider_keys declared key_prefix as VARCHAR(10) so the
display prefix (first 4 + "****" + last 4 = 12 chars) would not fit.  The
SQLAlchemy model in app/models/provider.py was later changed to String(20) to
match the real data shape, but no migration tracked the change — leaving the
deployed DB with the narrower column.

This migration widens the column to VARCHAR(20) so the model and DB agree.

Note: the existing data (12-char prefixes like 'sk-8****fb37') survives the
upgrade.  The downgrade is lossy: any prefix longer than 10 chars will be
truncated by PostgreSQL, so the truncated-to-10-chars prefix may no longer
uniquely identify the underlying key.  Downgrade is intentionally still
provided to keep migrations reversible in the same direction they were
applied (revision history) but should not be run in production.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "12b1c4d7ae30"
down_revision: Union[str, None] = "d8f5f38e52d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "provider_keys",
        "key_prefix",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Lossy: any prefix >10 chars will be truncated by PostgreSQL.  See module
    # docstring for the rationale on still providing a downgrade.
    op.execute(
        "ALTER TABLE provider_keys ALTER COLUMN key_prefix TYPE varchar(10) "
        "USING substring(key_prefix FROM 1 FOR 10)"
    )

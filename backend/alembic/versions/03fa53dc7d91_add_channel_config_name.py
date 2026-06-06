"""add channel config name

Revision ID: 03fa53dc7d91
Revises: dc16e024a564
Create Date: 2026-06-06 18:36:35.715789
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '03fa53dc7d91'
down_revision: Union[str, None] = 'dc16e024a564'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column as nullable first
    op.add_column('channel_configs', sa.Column('name', sa.String(50), nullable=True))

    # Backfill with provider name
    op.execute("""
        UPDATE channel_configs
        SET name = providers.name
        FROM providers
        WHERE channel_configs.provider_id = providers.id
    """)

    # For any remaining NULL (e.g. provider deleted), use a placeholder
    op.execute("""
        UPDATE channel_configs SET name = '默认渠道' WHERE name IS NULL
    """)

    # Make NOT NULL
    op.alter_column('channel_configs', 'name', nullable=False)


def downgrade() -> None:
    op.drop_column('channel_configs', 'name')

"""remove provider_id from model, add provider_model_id to channel_config

Revision ID: dc16e024a564
Revises: a1b5b82a1351
Create Date: 2026-06-06 16:42:59.975009

This migration:
  1. Adds provider_model_id to channel_configs (allows NULL initially)
  2. Backfills from models.provider_model_id
  3. Sets NOT NULL on channel_configs.provider_model_id
  4. Drops provider_id and provider_model_id from models
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'dc16e024a564'
down_revision: Union[str, None] = 'a1b5b82a1351'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add provider_model_id to channel_configs (nullable initially)
    op.add_column('channel_configs',
                  sa.Column('provider_model_id', sa.String(200), nullable=True))

    # 2. Backfill from models
    op.execute("""
        UPDATE channel_configs
        SET provider_model_id = models.provider_model_id
        FROM models
        WHERE channel_configs.model_id = models.id
    """)

    # 3. Set NOT NULL
    op.alter_column('channel_configs', 'provider_model_id',
                    existing_type=sa.String(200), nullable=False)

    # 4. Drop columns from models
    with op.batch_alter_table('models') as batch_op:
        batch_op.drop_column('provider_id')
        batch_op.drop_column('provider_model_id')


def downgrade() -> None:
    # Reverse: add columns back to models
    op.add_column('models',
                  sa.Column('provider_model_id', sa.String(200), nullable=True))
    op.add_column('models',
                  sa.Column('provider_id', sa.Integer(), nullable=True))

    # Reverse backfill models.provider_model_id from channel_configs
    op.execute("""
        UPDATE models
        SET provider_model_id = channel_configs.provider_model_id
        FROM channel_configs
        WHERE models.id = channel_configs.model_id
          AND channel_configs.is_default = TRUE
    """)

    # Drop channel_configs.provider_model_id
    op.drop_column('channel_configs', 'provider_model_id')

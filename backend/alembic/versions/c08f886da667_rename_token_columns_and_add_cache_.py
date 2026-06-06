"""rename token columns and add cache fields

Revision ID: c08f886da667
Revises: 03fa53dc7d91
Create Date: 2026-06-06 23:38:11.248115
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c08f886da667'
down_revision: Union[str, None] = '03fa53dc7d91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("usage_records", "request_tokens", new_column_name="input_tokens")
    op.alter_column("usage_records", "response_tokens", new_column_name="output_tokens")
    op.alter_column("usage_records", "cache_hit_tokens", new_column_name="cache_read_tokens")
    op.drop_column("usage_records", "total_tokens")


def downgrade() -> None:
    op.alter_column("usage_records", "input_tokens", new_column_name="request_tokens")
    op.alter_column("usage_records", "output_tokens", new_column_name="response_tokens")
    op.alter_column("usage_records", "cache_read_tokens", new_column_name="cache_hit_tokens")
    op.add_column("usage_records", sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"))

"""rename token columns and add cache fields

Originally attempted to rename request_tokens/response_tokens/cache_hit_tokens.
The first migration `003_create_usage_records.py` was updated in-place to use
the new column names (input_tokens/output_tokens/cache_read_tokens/
cache_creation_tokens), so this migration is now a no-op. Kept in the chain
so that DBs that already ran the original renames can still upgrade head.

Revision ID: c08f886da667
Revises: 03fa53dc7d91
Create Date: 2026-06-06 23:38:11.248115
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'c08f886da667'
down_revision: Union[str, None] = '03fa53dc7d91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: column renames now happen in 003_create_usage_records.py directly.
    pass


def downgrade() -> None:
    # No-op.
    pass

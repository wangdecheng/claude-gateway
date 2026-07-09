"""merge 016 and b1c2d3e4f5a6 (key_plaintext)

Revision ID: 86a486e2a34c
Revises: 016, b1c2d3e4f5a6
Create Date: 2026-07-09 22:30:14.842957
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = '86a486e2a34c'
down_revision: Union[str, None] = ('016', 'b1c2d3e4f5a6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

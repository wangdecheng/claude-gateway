"""add token_coefficient_configs table (global + per-model override) and seed default global row

Revision ID: 016
Revises: 015
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_coefficient_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope_type", sa.String(10), nullable=False),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "coefficient",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("model_id", name="uq_token_coefficient_configs_model_id"),
        sa.CheckConstraint(
            "coefficient > 0 AND coefficient <= 1",
            name="ck_token_coefficient_configs_range",
        ),
        sa.CheckConstraint(
            "(scope_type = 'global' AND model_id IS NULL) OR "
            "(scope_type = 'model' AND model_id IS NOT NULL)",
            name="ck_token_coefficient_configs_scope_model",
        ),
    )
    # Seed default global row
    op.execute(
        "INSERT INTO token_coefficient_configs (scope_type, coefficient) "
        "VALUES ('global', 1.0)"
    )


def downgrade() -> None:
    op.drop_table("token_coefficient_configs")

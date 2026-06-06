"""create provider_keys table

Revision ID: 010
Revises: 009
Create Date: 2026-05-31

Epic 4 Story 4.2: ProviderKey table for encrypted upstream key pool.
Keys are AES-256-GCM encrypted at rest.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("providers.id"),
            nullable=False,
        ),
        sa.Column(
            "key_encrypted",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM ciphertext (base64-encoded)",
        ),
        sa.Column(
            "key_prefix",
            sa.String(10),
            nullable=False,
            comment="First 4 + last 4 chars for masked display",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
            comment="active | revoked (soft-delete, never re-enable)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_provider_keys_provider_id", "provider_keys", ["provider_id"])
    op.create_index("idx_provider_keys_status", "provider_keys", ["status"])


def downgrade() -> None:
    op.drop_index("idx_provider_keys_status", table_name="provider_keys")
    op.drop_index("idx_provider_keys_provider_id", table_name="provider_keys")
    op.drop_table("provider_keys")

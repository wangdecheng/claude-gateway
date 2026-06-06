"""add auth_header, api_key_env, adapter to providers

Revision ID: 009
Revises: 008
Create Date: 2026-05-31

Epic 2 Story 2.4: Extend Provider model with upstream auth and protocol
adapter configuration so the proxy can make real HTTP calls.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column(
            "auth_header",
            sa.String(50),
            nullable=False,
            server_default="Authorization",
            comment="HTTP header name for auth, e.g. 'x-api-key' or 'Authorization'",
        ),
    )
    op.add_column(
        "providers",
        sa.Column(
            "api_key_env",
            sa.String(100),
            nullable=False,
            server_default="",
            comment="Environment variable name holding the upstream API key",
        ),
    )
    op.add_column(
        "providers",
        sa.Column(
            "adapter",
            sa.String(50),
            nullable=False,
            server_default="openai-chat-completions",
            comment="Protocol adapter: 'openai-chat-completions' or 'anthropic-messages'",
        ),
    )


def downgrade() -> None:
    op.drop_column("providers", "adapter")
    op.drop_column("providers", "api_key_env")
    op.drop_column("providers", "auth_header")

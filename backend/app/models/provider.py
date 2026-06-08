from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (
        UniqueConstraint("name", "channel_name", name="uq_providers_name_channel_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Display name for this provider within its channel grouping",
    )
    multiplier: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
        comment="Pricing multiplier applied when billing through this provider",
    )
    api_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Upstream auth configuration
    auth_header: Mapped[str] = mapped_column(
        String(50),
        default="Authorization",
        nullable=False,
        comment="HTTP header name for auth, e.g. 'x-api-key' or 'Authorization'",
    )
    api_key_env: Mapped[str] = mapped_column(
        String(100),
        default="",
        nullable=False,
        comment="Environment variable name holding the upstream API key",
    )
    adapter: Mapped[str] = mapped_column(
        String(50),
        default="openai-chat-completions",
        nullable=False,
        comment="Protocol adapter: 'openai-chat-completions' or 'anthropic-messages'",
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderKey(Base):
    """Encrypted upstream API key belonging to a provider.

    Keys are AES-256-GCM encrypted at rest.  The plaintext value is only
    available in memory after decryption; it is never logged or returned
    in API responses.
    """

    __tablename__ = "provider_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("providers.id"), nullable=False)
    key_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False, comment="AES-256-GCM ciphertext (base64-encoded)"
    )
    key_prefix: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="First 4 + last 4 chars for masked display (max 12 chars)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        comment="active | revoked (soft-delete, never re-enable)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

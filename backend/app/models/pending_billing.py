"""PendingBilling ORM — async billing queue between proxy and worker."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator

from app.database import Base


class GUID(TypeDecorator):
    """Cross-dialect UUID stored as CHAR(36) at the DB level.

    Python type is ``uuid.UUID``; on the wire it is always a 36-char string.
    This avoids the PostgreSQL native-UUID vs string-column type mismatch
    that bites when asyncpg generates a ``$1::UUID`` cast against a CHAR(36)
    column.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        # Always send a 36-char string, regardless of dialect.
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class PendingBilling(Base):
    __tablename__ = "pending_billings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), unique=True, nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    api_key_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("api_keys.id"), nullable=False
    )
    model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("models.id"), nullable=False
    )
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channel_configs.id"), nullable=False
    )
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id"), nullable=False
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Upstream Anthropic message.id from message_start event (e.g. "msg_01ABCxyz...").
    # Lets us cross-reference call records with Claude Code JSONL session files
    # and with the upstream provider's logs.
    upstream_message_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending | settled | dead
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

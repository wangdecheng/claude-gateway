from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False)  # "sk-a1b2c3"
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 明文保存 sk，使前端可以随时复制完整 key（鉴权仍走 key_hash）。
    key_plaintext: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("providers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Bound provider; NULL = legacy auto behavior",
    )

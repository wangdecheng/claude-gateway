from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChannelKey(Base):
    __tablename__ = "channel_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id"), nullable=False
    )
    provider_key_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("provider_keys.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider_id", "provider_key_id", name="uq_provider_key"),
    )

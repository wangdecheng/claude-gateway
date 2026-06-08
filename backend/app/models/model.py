from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_price: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # micro-yuan per 1K tokens
    output_price: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # micro-yuan per 1K tokens
    cache_read_price: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="Cache read price in micro yuan per 1K tokens",
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

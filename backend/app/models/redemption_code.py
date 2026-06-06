"""Redemption code and usage ORM models."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RedemptionCode(Base):
    __tablename__ = "redemption_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    code_prefix: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 单位: 分
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)
    # 'issued' → 'used' → 'expired'
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("amount > 0", name="ck_redemption_codes_amount_positive"),)


class RedemptionUsage(Base):
    __tablename__ = "redemption_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    code_id: Mapped[int] = mapped_column(Integer, ForeignKey("redemption_codes.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 单位: 分
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

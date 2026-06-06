"""Payment service — order creation, callback handling, history."""

import hashlib
import hmac
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import AppException
from app.models.payment_record import PaymentRecord
from app.models.user import User

MIN_AMOUNT = 100  # ¥1.00
MAX_AMOUNT = 500_000  # ¥5,000.00


def sign_callback(order_id: int, transaction_id: str) -> str:
    """Generate HMAC-SHA256 signature for callback URL verification."""
    payload = f"{order_id}:{transaction_id}"
    return hmac.new(
        settings.jwt_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def verify_callback_signature(order_id: int, transaction_id: str, signature: str) -> bool:
    """Verify callback HMAC signature. Uses constant-time comparison."""
    expected = sign_callback(order_id, transaction_id)
    return hmac.compare_digest(expected, signature)


async def create_order(
    db: AsyncSession,
    user_id: int,
    amount: int,
    method: str,
) -> PaymentRecord:
    """Create a payment order.

    Returns the PaymentRecord with status='pending'.
    """
    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        raise AppException(
            400,
            f"充值金额需在 ¥{MIN_AMOUNT / 100:.2f} ~ ¥{MAX_AMOUNT / 100:.2f} 之间",
            "INVALID_AMOUNT",
        )
    if method not in ("alipay", "wechat"):
        raise AppException(400, "不支持的支付方式", "INVALID_PAYMENT_METHOD")

    # Verify user exists and is active
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise AppException(404, "用户不存在", "USER_NOT_FOUND")
    if user.status != "active":
        raise AppException(403, "账号已被禁用", "USER_DISABLED")

    record = PaymentRecord(
        user_id=user_id,
        amount=amount,
        method=method,
        status="pending",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def handle_callback(
    db: AsyncSession,
    method: str,
    order_id: int,
    transaction_id: str,
) -> PaymentRecord:
    """Handle payment callback with idempotency.

    On first successful callback:
      - Updates PaymentRecord status → 'success'
      - Credits user balance
      - Records transaction_id

    On duplicate callback (same transaction_id): returns existing record (idempotent).
    """
    # 1. Idempotency check (locked to prevent TOCTOU race)
    existing_result = await db.execute(
        select(PaymentRecord)
        .where(PaymentRecord.transaction_id == transaction_id)
        .with_for_update()
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing

    # 2. Lock and validate the order
    order_result = await db.execute(
        select(PaymentRecord).where(PaymentRecord.id == order_id).with_for_update()
    )
    record = order_result.scalar_one_or_none()
    if not record:
        raise AppException(404, "订单不存在", "ORDER_NOT_FOUND")
    if record.status != "pending":
        raise AppException(400, "订单已处理", "ORDER_ALREADY_PROCESSED")
    if record.method != method:
        raise AppException(400, "支付方式不匹配", "PAYMENT_METHOD_MISMATCH")

    # 3. Lock user row and credit balance
    user_result = await db.execute(select(User).where(User.id == record.user_id).with_for_update())
    user = user_result.scalar_one_or_none()
    if not user:
        raise AppException(404, "用户不存在", "USER_NOT_FOUND")
    user.balance += record.amount

    # 4. Update payment record
    record.status = "success"
    record.transaction_id = transaction_id
    record.updated_at = datetime.now(timezone.utc)

    await db.commit()
    return record


async def get_payment_history(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[PaymentRecord], int]:
    """Get paginated payment history for a user."""
    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(PaymentRecord).where(PaymentRecord.user_id == user_id)
    )
    total = count_result.scalar() or 0

    # Paginated results
    items_result = await db.execute(
        select(PaymentRecord)
        .where(PaymentRecord.user_id == user_id)
        .order_by(PaymentRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(items_result.scalars().all())

    return items, total

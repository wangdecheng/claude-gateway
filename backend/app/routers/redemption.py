"""Redemption API — POST /api/redeem, GET /api/redeem/history."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.common import ErrorResponse
from app.schemas.redemption import (
    RedeemRequest,
    RedeemResponse,
    RedemptionHistoryResponse,
)
from app.services.redemption_service import get_redemption_history, redeem

router = APIRouter(prefix="/api/redeem", tags=["redemption"])


@router.post(
    "",
    response_model=RedeemResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Redemption failed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def redeem_code(
    body: RedeemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a code and credit the user's balance.

    Requires JWT cookie authentication (user-scoped).
    """
    amount, balance = await redeem(db, user.id, body.code)

    return RedeemResponse(
        amount=amount,
        balance=balance,
        message=f"余额已到账 ¥{amount / 100:.2f}",
    )


@router.get(
    "/history",
    response_model=RedemptionHistoryResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def redemption_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's redemption history, newest first."""
    items = await get_redemption_history(db, user.id)
    return RedemptionHistoryResponse(items=items)

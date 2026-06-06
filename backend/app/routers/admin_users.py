"""Admin user management router."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.user import User
from app.schemas.admin_user import AdminUserResponse

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


def _format_user(user: User) -> dict:
    """Format ORM user to the public admin response shape."""
    return {
        "id": user.id,
        "email": user.email,
        "balance": user.balance,
        "role": user.role,
        "status": user.status,
        "createdAt": user.created_at.isoformat(),
    }


@router.get("", response_model=list[AdminUserResponse])
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users for admin management."""
    result = await db.execute(select(User).order_by(User.id.asc()))
    return [_format_user(user) for user in result.scalars().all()]


@router.patch("/{user_id}/status", response_model=AdminUserResponse)
async def toggle_user_status(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a user's active/disabled status."""
    if user_id == admin.id:
        raise AppException(
            status_code=400,
            error="不能禁用当前登录的管理员账号",
            code="CANNOT_DISABLE_SELF",
        )

    user = await db.get(User, user_id)
    if user is None:
        raise AppException(status_code=404, error="用户不存在", code="USER_NOT_FOUND")

    user.status = "disabled" if user.status == "active" else "active"
    await db.commit()
    await db.refresh(user)
    return _format_user(user)

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.schemas.common import ErrorResponse
from app.services.auth_service import (
    change_password,
    forgot_password,
    generate_jwt,
    login,
    register,
    reset_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookie(response: JSONResponse, token: str) -> None:
    response.set_cookie(
        key="high_api_session",
        value=token,
        httponly=True,
        secure=False,  # Set True in production
        samesite="lax",
        max_age=86400,  # 24 hours
    )


def _clear_auth_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        key="high_api_session",
        httponly=True,
        secure=False,
        samesite="lax",
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    responses={
        409: {"model": ErrorResponse, "description": "Email already registered"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def register_user(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await register(db, email=body.email, password=body.password)

    token = generate_jwt(user.id, user.role)
    response = JSONResponse(
        status_code=201,
        content={
            "user_id": user.id,
            "email": user.email,
            "balance": user.balance,
            "role": user.role,
        },
    )
    _set_auth_cookie(response, token)
    return response


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def login_user(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await login(db, email=body.email, password=body.password)

    token = generate_jwt(user.id, user.role)
    response = JSONResponse(
        status_code=200,
        content={
            "user_id": user.id,
            "email": user.email,
            "balance": user.balance,
            "role": user.role,
        },
    )
    _set_auth_cookie(response, token)
    return response


@router.get(
    "/me",
    response_model=AuthResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_me(user: User = Depends(get_current_user)):
    return {
        "user_id": user.id,
        "email": user.email,
        "balance": user.balance,
        "role": user.role,
    }


@router.post("/logout")
async def logout():
    response = JSONResponse(status_code=200, content={"message": "已退出登录"})
    _clear_auth_cookie(response)
    return response


@router.post(
    "/change-password",
    responses={
        400: {"model": ErrorResponse, "description": "Wrong current password"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def change_password_endpoint(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await change_password(
        db, user=user, current_password=body.current_password, new_password=body.new_password
    )
    return {"message": "密码已修改"}


@router.post(
    "/forgot-password",
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
)
async def forgot_password_endpoint(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Always returns 200 to prevent email enumeration.
    In dev mode, the reset token is returned for testing purposes."""
    token = await forgot_password(db, email=body.email)
    # In dev: return token so developer can use it directly
    # In production: send token via email and return generic message
    if token:
        return {"message": "如果该邮箱已注册，重置链接已发送", "token": token}
    return {"message": "如果该邮箱已注册，重置链接已发送"}


@router.post(
    "/reset-password",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid or expired token"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def reset_password_endpoint(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    await reset_password(db, token=body.token, new_password=body.new_password)
    return {"message": "密码已重置，请使用新密码登录"}

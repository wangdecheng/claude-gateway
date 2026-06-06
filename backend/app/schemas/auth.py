from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)
    confirm_password: str = Field(..., alias="confirmPassword")

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少8位")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("两次密码不一致")
        return v

    model_config = {"populate_by_name": True}


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    user_id: int
    email: str
    balance: int
    role: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, alias="currentPassword")
    new_password: str = Field(..., min_length=1, alias="newPassword")
    confirm_new_password: str = Field(..., min_length=1, alias="confirmNewPassword")

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少8位")
        return v

    @field_validator("confirm_new_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("两次密码不一致")
        return v

    model_config = {"populate_by_name": True}


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1, alias="newPassword")
    confirm_new_password: str = Field(..., min_length=1, alias="confirmNewPassword")

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少8位")
        return v

    @field_validator("confirm_new_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("两次密码不一致")
        return v

    model_config = {"populate_by_name": True}

"""Redemption-related request/response schemas."""

from pydantic import BaseModel, Field


class RedeemRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="兑换码")


class RedeemResponse(BaseModel):
    amount: int = Field(..., description="兑换金额（分）")
    balance: int = Field(..., description="兑换后余额（分）")
    message: str = Field(..., description="成功消息")


class RedemptionHistoryItem(BaseModel):
    id: int
    code_masked: str = Field(..., alias="codeMasked")
    amount: int
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


class RedemptionHistoryResponse(BaseModel):
    items: list[RedemptionHistoryItem]


class AdminRedemptionCreateRequest(BaseModel):
    amount: int = Field(..., gt=0, description="兑换金额（分）")
    expires_in_days: int = Field(
        5,
        alias="expiresInDays",
        gt=0,
        description="有效天数",
    )

    model_config = {"populate_by_name": True}


class AdminRedemptionCreateResponse(BaseModel):
    id: int
    code: str
    code_prefix: str = Field(..., alias="codePrefix")
    amount: int
    status: str
    expires_at: str = Field(..., alias="expiresAt")
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


class AdminRedemptionListItem(BaseModel):
    """Single row of the admin redemption-history list.

    `status` is the *effective* status: if the DB row is still `issued`
    but `expires_at` has passed, this field reports `expired` (the DB
    row itself is left untouched — the list endpoint is read-only).
    """

    id: int
    code_prefix: str = Field(..., alias="codePrefix")
    amount: int
    status: str  # issued | used | expired
    expires_at: str = Field(..., alias="expiresAt")
    created_at: str = Field(..., alias="createdAt")
    created_by_email: str | None = Field(None, alias="createdByEmail")
    used_by_email: str | None = Field(None, alias="usedByEmail")
    used_at: str | None = Field(None, alias="usedAt")

    model_config = {"populate_by_name": True}

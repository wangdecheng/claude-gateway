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

"""Payment request/response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CreateOrderRequest(BaseModel):
    amount: int = Field(..., gt=0, description="充值金额（分）")
    method: str = Field(..., description="支付方式: alipay | wechat")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        if v not in ("alipay", "wechat"):
            raise ValueError("不支持的支付方式，请选择 alipay 或 wechat")
        return v


class CreateOrderResponse(BaseModel):
    order_id: int = Field(..., alias="orderId")
    amount: int
    method: str
    status: str
    pay_url: str = Field(..., alias="payUrl")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {"from_attributes": True, "populate_by_name": True}


class PaymentCallbackResponse(BaseModel):
    order_id: int = Field(..., alias="orderId")
    amount: int
    method: str
    status: str
    transaction_id: str = Field(..., alias="transactionId")

    model_config = {"from_attributes": True, "populate_by_name": True}


class PaymentHistoryItem(BaseModel):
    id: int
    amount: int
    method: str
    status: str
    transaction_id: Optional[str] = Field(None, alias="transactionId")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {"from_attributes": True, "populate_by_name": True}


class PaymentHistoryResponse(BaseModel):
    items: list[PaymentHistoryItem]
    total: int
    page: int
    page_size: int = Field(..., alias="pageSize")

    model_config = {"populate_by_name": True}

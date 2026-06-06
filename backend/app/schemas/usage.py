from datetime import datetime

from pydantic import BaseModel, Field


class DailyStat(BaseModel):
    date: str
    calls: int
    tokens: int
    cost_cents: int = Field(..., alias="costCents")

    model_config = {"populate_by_name": True}


class UsageStatsResponse(BaseModel):
    today_calls: int = Field(..., alias="todayCalls")
    today_tokens: int = Field(..., alias="todayTokens")
    today_cost_cents: int = Field(..., alias="todayCostCents")
    active_keys: int = Field(..., alias="activeKeys")
    balance_cents: int = Field(..., alias="balanceCents")
    daily: list[DailyStat]

    model_config = {"populate_by_name": True}


class UsageRecordResponse(BaseModel):
    id: int
    model: str
    request_tokens: int = Field(..., alias="requestTokens")
    response_tokens: int = Field(..., alias="responseTokens")
    total_tokens: int = Field(..., alias="totalTokens")
    cost_cents: int = Field(..., alias="costCents")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


class UsageHistoryResponse(BaseModel):
    records: list[UsageRecordResponse]
    total: int
    page: int
    page_size: int = Field(..., alias="pageSize")

    model_config = {"populate_by_name": True}

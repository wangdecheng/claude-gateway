"""Pydantic schemas for the admin token coefficient endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class TokenCoefficientBase(BaseModel):
    coefficient: float = Field(..., gt=0, le=1)


class TokenCoefficientGlobalUpdate(TokenCoefficientBase):
    """Request body for PUT /api/admin/token-coefficients/global."""


class TokenCoefficientModelUpsert(TokenCoefficientBase):
    """Request body for PUT /api/admin/token-coefficients/models/{modelId}."""


class TokenCoefficientModelOut(BaseModel):
    model_id: int = Field(..., alias="modelId")
    model_name: str = Field(..., alias="modelName")
    model_public_name: str = Field(..., alias="modelPublicName")
    coefficient: float
    updated_at: datetime = Field(..., alias="updatedAt")
    updated_by_username: str | None = Field(None, alias="updatedByUsername")

    model_config = {"populate_by_name": True}


class TokenCoefficientGlobalOut(BaseModel):
    coefficient: float
    updated_at: datetime = Field(..., alias="updatedAt")
    updated_by_username: str | None = Field(None, alias="updatedByUsername")

    model_config = {"populate_by_name": True}


class TokenCoefficientsOverview(BaseModel):
    global_coefficient: float = Field(..., alias="globalCoefficient")
    global_meta: TokenCoefficientGlobalOut = Field(..., alias="globalMeta")
    overrides: list[TokenCoefficientModelOut]

    model_config = {"populate_by_name": True}

"""Admin (model ↔ provider) route management schemas.

The "channel" admin endpoint manages ModelProviderRoute rows. Channel name
and multiplier are properties of the Provider (set via /api/admin/providers),
not the route itself.
"""

from pydantic import BaseModel, Field, model_validator


class ChannelCreate(BaseModel):
    """Schema for creating a (model, provider) routing entry."""

    model_id: int = Field(..., gt=0, alias="modelId")
    provider_id: int = Field(..., gt=0, alias="providerId")
    provider_model: str = Field(
        ...,
        min_length=1,
        max_length=200,
        alias="providerModel",
        description="Upstream model name at the provider, e.g. 'claude-sonnet-4-6-20250501'",
    )
    is_default: bool = Field(False, alias="isDefault")

    model_config = {"populate_by_name": True}


class ChannelUpdate(BaseModel):
    """Schema for updating an existing route. All fields optional."""

    provider_model: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        alias="providerModel",
    )
    is_default: bool | None = Field(None, alias="isDefault")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _require_at_least_one_field(self):
        if self.provider_model is None and self.is_default is None:
            raise ValueError("至少需要提供 providerModel 或 isDefault 之一")
        return self


class AdminChannelResponse(BaseModel):
    """Admin channel/route list item."""

    id: int
    model_id: int = Field(..., alias="modelId")
    model_name: str = Field(..., alias="modelName")
    model_status: str = Field(..., alias="modelStatus")
    provider_id: int = Field(..., alias="providerId")
    provider_name: str = Field(..., alias="providerName")
    provider_channel_name: str = Field(..., alias="providerChannelName")
    provider_multiplier: float = Field(..., alias="providerMultiplier")
    provider_status: str = Field(..., alias="providerStatus")
    provider_model: str = Field(..., alias="providerModel")
    is_default: bool = Field(..., alias="isDefault")
    status: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}

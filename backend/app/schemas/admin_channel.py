"""Admin channel multiplier configuration schemas."""

from pydantic import BaseModel, Field, model_validator


class ChannelCreate(BaseModel):
    """Schema for creating a model-provider channel config."""

    model_id: int = Field(..., gt=0, alias="modelId")
    provider_id: int = Field(..., gt=0, alias="providerId")
    provider_model_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        alias="providerModelId",
        description="Upstream model name at the provider, e.g. 'deepseekV4-pro'",
    )
    multiplier: float = Field(..., gt=0)
    is_default: bool = Field(False, alias="isDefault")

    model_config = {"populate_by_name": True}


class ChannelUpdate(BaseModel):
    """Schema for updating an existing channel config."""

    provider_model_id: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        alias="providerModelId",
    )
    multiplier: float | None = Field(None, gt=0)
    is_default: bool | None = Field(None, alias="isDefault")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _require_at_least_one_field(self):
        if (
            self.provider_model_id is None
            and self.multiplier is None
            and self.is_default is None
        ):
            raise ValueError("至少需要提供 providerModelId、multiplier 或 isDefault 之一")
        return self


class AdminChannelResponse(BaseModel):
    """Admin channel list item."""

    id: int
    model_id: int = Field(..., alias="modelId")
    model_name: str = Field(..., alias="modelName")
    model_status: str = Field(..., alias="modelStatus")
    provider_id: int = Field(..., alias="providerId")
    provider_name: str = Field(..., alias="providerName")
    provider_status: str = Field(..., alias="providerStatus")
    provider_model_id: str = Field(..., alias="providerModelId")
    multiplier: float
    is_default: bool = Field(..., alias="isDefault")
    status: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}

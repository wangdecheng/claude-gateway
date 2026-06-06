from typing import Optional

from pydantic import BaseModel, Field


class ChannelInfo(BaseModel):
    id: int
    provider_name: str = Field(..., alias="providerName")
    multiplier: float
    is_default: bool = Field(..., alias="isDefault")

    model_config = {"populate_by_name": True}


class ModelWithChannels(BaseModel):
    id: int
    public_name: str = Field(..., alias="publicName")
    description: Optional[str] = None
    input_price: int = Field(..., alias="inputPrice")
    output_price: int = Field(..., alias="outputPrice")
    channels: list[ChannelInfo]

    model_config = {"populate_by_name": True}


class ModelDetail(BaseModel):
    id: int
    public_name: str = Field(..., alias="publicName")
    provider_name: str = Field(..., alias="providerName")
    provider_model_id: str = Field(..., alias="providerModelId")
    description: Optional[str] = None
    input_price: int = Field(..., alias="inputPrice")
    output_price: int = Field(..., alias="outputPrice")
    status: str
    channels: list[ChannelInfo]
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}

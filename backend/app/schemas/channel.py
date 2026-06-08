"""User-side channel schemas — never expose provider.name."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserChannelInfo(BaseModel):
    id: int
    channel_name: str = Field(..., alias="channelName")
    multiplier: float
    is_default: bool = Field(..., alias="isDefault")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ChannelModelRow(BaseModel):
    id: int
    public_name: str = Field(..., alias="publicName")
    description: Optional[str] = None
    input_price: float = Field(..., alias="inputPrice")
    output_price: float = Field(..., alias="outputPrice")
    input_base_price: float = Field(..., alias="inputBasePrice")
    output_base_price: float = Field(..., alias="outputBasePrice")

    model_config = ConfigDict(populate_by_name=True)


class UserChannelWithModels(BaseModel):
    channel: UserChannelInfo
    models: list[ChannelModelRow]

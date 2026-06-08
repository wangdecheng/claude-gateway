from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ChannelInfo(BaseModel):
    id: int
    channel_name: str = Field(..., alias="channelName")
    multiplier: float
    is_default: bool = Field(..., alias="isDefault")

    model_config = ConfigDict(populate_by_name=True)


class ModelWithChannels(BaseModel):
    id: int
    public_name: str = Field(..., alias="publicName")
    description: Optional[str] = None
    input_price: int = Field(..., alias="inputPrice")
    output_price: int = Field(..., alias="outputPrice")
    channels: list[ChannelInfo]

    model_config = ConfigDict(populate_by_name=True)


class ModelDetail(BaseModel):
    id: int
    public_name: str = Field(..., alias="publicName")
    description: Optional[str] = None
    input_price: int = Field(..., alias="inputPrice")
    output_price: int = Field(..., alias="outputPrice")
    status: str
    channels: list[ChannelInfo]
    created_at: str = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    channel_id: int = Field(..., gt=0, alias="channelId")

    model_config = ConfigDict(populate_by_name=True)


class KeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str = Field(..., alias="keyPrefix")
    status: str
    created_at: datetime = Field(..., alias="createdAt")
    last_used_at: Optional[datetime] = Field(None, alias="lastUsedAt")
    channel_id: Optional[int] = Field(None, alias="channelId")
    channel_name: Optional[str] = Field(None, alias="channelName")

    model_config = ConfigDict(populate_by_name=True)


class CreateKeyResponse(KeyResponse):
    raw_key: str = Field(..., alias="rawKey")


class UpdateKeyRequest(BaseModel):
    """Schema for updating an existing key's bound channel.

    channelId is required: a positive int switches the binding, null clears it
    (back to 'auto, by model default').
    """

    channel_id: int | None = Field(..., alias="channelId")

    model_config = ConfigDict(populate_by_name=True)

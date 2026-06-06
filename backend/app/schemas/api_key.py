from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class KeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str = Field(..., alias="keyPrefix")
    status: str
    created_at: datetime = Field(..., alias="createdAt")
    last_used_at: Optional[datetime] = Field(None, alias="lastUsedAt")

    model_config = {"populate_by_name": True}


class CreateKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str = Field(..., alias="keyPrefix")
    raw_key: str = Field(..., alias="rawKey")
    status: str
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}

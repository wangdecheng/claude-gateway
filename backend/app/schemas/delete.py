"""Shared response schemas for delete operations."""

from pydantic import BaseModel, Field


class DeleteResponse(BaseModel):
    """Returned by DELETE endpoints for model/provider/channel."""

    deleted: bool = Field(..., description="Always true on success")
    method: str = Field(..., description="'hard' or 'soft'")
    id: int = Field(..., description="ID of the deleted entity")

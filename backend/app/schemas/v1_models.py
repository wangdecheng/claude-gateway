"""Anthropic-compatible /v1/models response schemas."""

from pydantic import BaseModel


class ModelData(BaseModel):
    """A single model entry in the Anthropic Models List response."""

    type: str = "model"
    id: str
    display_name: str
    created_at: str
    provider_status: str | None = None


class ListModelsResponse(BaseModel):
    """Anthropic-compatible GET /v1/models response."""

    data: list[ModelData]
    has_more: bool = False
    first_id: str | None = None
    last_id: str | None = None

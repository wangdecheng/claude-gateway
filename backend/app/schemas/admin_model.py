"""Admin model management schemas."""

from pydantic import BaseModel, Field, field_validator


class ModelCreate(BaseModel):
    """Schema for creating a new model."""

    public_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        alias="publicName",
        description="Public display name for the model",
    )
    description: str | None = Field(None, max_length=2000)
    input_price: int = Field(
        ..., ge=0, alias="inputPrice", description="Input price in micro-yuan per 1K tokens"
    )
    output_price: int = Field(
        ..., ge=0, alias="outputPrice", description="Output price in micro-yuan per 1K tokens"
    )

    model_config = {"populate_by_name": True}

    @field_validator("public_name")
    @classmethod
    def public_name_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("公开名称不能为空")
        return stripped


class ModelUpdate(BaseModel):
    """Schema for updating an existing model.

    All fields optional — only provided fields are updated.
    """

    public_name: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        alias="publicName",
    )
    description: str | None = Field(None, max_length=2000)
    input_price: int | None = Field(None, ge=0, alias="inputPrice")
    output_price: int | None = Field(None, ge=0, alias="outputPrice")

    model_config = {"populate_by_name": True}

    @field_validator("public_name")
    @classmethod
    def public_name_not_empty_if_set(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("公开名称不能为空")
        return v.strip() if v else v


class AdminModelResponse(BaseModel):
    """Model entry for the admin model list."""

    id: int
    public_name: str = Field(..., alias="publicName")
    description: str | None = None
    input_price: int = Field(..., alias="inputPrice")
    output_price: int = Field(..., alias="outputPrice")
    status: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


class ProviderOption(BaseModel):
    """Lightweight provider entry for admin dropdowns."""

    id: int
    name: str

"""Admin provider management schemas."""

from pydantic import BaseModel, Field, field_validator

# ── Provider CRUD ────────────────────────────────────────────────────


class ProviderCreate(BaseModel):
    """Schema for creating a new provider with optional initial keys."""

    name: str = Field(..., min_length=1, max_length=100)
    channel_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        alias="channelName",
        description="Display name for the channel this provider exposes (e.g. '主力线路', 'awsq').",
    )
    multiplier: float = Field(
        1.0,
        gt=0,
        description="Pricing multiplier — final price = model_price × multiplier.",
    )
    api_base_url: str = Field(
        ...,
        min_length=1,
        max_length=500,
        alias="apiBaseUrl",
    )
    auth_header: str = Field(
        "Authorization",
        min_length=1,
        max_length=50,
        alias="authHeader",
    )
    adapter: str = Field(
        "openai-chat-completions",
        pattern=r"^(openai-chat-completions|anthropic-messages)$",
    )
    keys: list[str] | None = Field(
        None,
        max_length=100,
        description="Optional upstream API keys (one per string, newline-separated in UI)",
    )

    model_config = {"populate_by_name": True}

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("供应商名称不能为空")
        return stripped

    @field_validator("channel_name")
    @classmethod
    def channel_name_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("渠道名不能为空")
        return stripped

    @field_validator("api_base_url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("API Base URL 不能为空")
        return stripped


class ProviderUpdate(BaseModel):
    """Schema for updating an existing provider. All fields optional.

    Per AC-3, only api_base_url, auth_header, and adapter are editable.
    Name changes are not supported via update to avoid uniqueness issues.
    Channel name and multiplier are editable so admins can re-tier pricing
    without recreating the provider.
    """

    channel_name: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        alias="channelName",
    )
    multiplier: float | None = Field(None, gt=0)
    api_base_url: str | None = Field(
        None,
        min_length=1,
        max_length=500,
        alias="apiBaseUrl",
    )
    auth_header: str | None = Field(
        None,
        min_length=1,
        max_length=50,
        alias="authHeader",
    )
    adapter: str | None = Field(
        None,
        pattern=r"^(openai-chat-completions|anthropic-messages)$",
    )

    model_config = {"populate_by_name": True}

    @field_validator("api_base_url")
    @classmethod
    def url_not_empty_if_set(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("API Base URL 不能为空")
        return v.strip() if v else v


class AdminProviderResponse(BaseModel):
    """Provider entry for the admin provider list."""

    id: int
    name: str
    channel_name: str = Field(..., alias="channelName")
    multiplier: float
    api_base_url: str = Field(..., alias="apiBaseUrl")
    auth_header: str = Field(..., alias="authHeader")
    adapter: str
    key_count: int = Field(..., alias="keyCount")
    active_key_count: int = Field(0, alias="activeKeyCount")
    status: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


# ── ProviderKey management ───────────────────────────────────────────


class ProviderKeyResponse(BaseModel):
    """A single provider key entry (masked — never exposes plaintext)."""

    id: int
    key_prefix: str = Field(
        ...,
        alias="keyPrefix",
        description="Masked key prefix for display, e.g. 'sk-a****b3f2'",
    )
    status: str
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}


class ProviderKeyCreate(BaseModel):
    """Schema for adding one or more keys to an existing provider."""

    keys: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="One or more upstream API key strings",
    )

    @field_validator("keys")
    @classmethod
    def keys_not_empty(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k.strip()]
        if not cleaned:
            raise ValueError("至少需要一把 Key")
        return cleaned


class ProviderKeyCreateResponse(BaseModel):
    """Response after adding keys — never returns plaintext values."""

    added: int = Field(..., description="Number of keys successfully added")
    key_prefixes: list[str] = Field(
        ...,
        alias="keyPrefixes",
        description="Masked prefixes for confirmation display",
    )

    model_config = {"populate_by_name": True}

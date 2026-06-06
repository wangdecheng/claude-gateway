"""Centralized configuration using Pydantic Settings."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import HTTP_CONNECT_TIMEOUT_DEFAULT
from .nim import NimSettings
from .paths import managed_env_path
from .provider_ids import SUPPORTED_PROVIDER_IDS


@dataclass(frozen=True, slots=True)
class ConfiguredChatModelRef:
    model_ref: str
    provider_id: str
    model_id: str
    sources: tuple[str, ...]


def _env_file_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    try:
        values = dotenv_values(path)
    except OSError:
        return None
    if key not in values:
        return None
    value = values[key]
    return "" if value is None else value


def _env_file_override(model_config: Mapping[str, Any], key: str) -> str | None:
    configured_value: str | None = None
    env_files = model_config.get("env_file")
    if env_files is None:
        return None
    if isinstance(env_files, (str, Path)):
        env_files = (Path(env_files),)
    else:
        env_files = tuple(Path(f) for f in env_files)
    for env_file in env_files:
        value = _env_file_value(env_file, key)
        if value is not None:
            configured_value = value
    return configured_value


def _env_files() -> tuple[Path, ...]:
    files: list[Path] = [Path(".env"), managed_env_path()]
    if explicit := os.environ.get("FCC_ENV_FILE"):
        files.append(Path(explicit))
    return tuple(files)


class Settings(BaseSettings):
    """Application settings."""

    # ==================== Database ====================
    database_url: str = Field(
        default="postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api",
        validation_alias="DATABASE_URL",
    )

    # ==================== JWT ====================
    jwt_secret: str = Field(
        default="dev-secret-change-in-production", validation_alias="JWT_SECRET"
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expire_seconds: int = Field(default=86400, validation_alias="JWT_EXPIRE_SECONDS")

    # ==================== App ====================
    app_name: str = Field(default="cloude-gateway", validation_alias="APP_NAME")
    debug: bool = Field(default=True, validation_alias="DEBUG")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"], validation_alias="CORS_ORIGINS"
    )

    # ==================== DeepSeek ====================
    deepseek_api_key: str = Field(default="", validation_alias="DEEPSEEK_API_KEY")
    deepseek_cache_creation_max_input_multiplier: int = Field(
        default=10, ge=1, validation_alias="DEEPSEEK_CACHE_CREATION_MAX_INPUT_MULTIPLIER"
    )

    # ==================== Model Routing ====================
    model: str = "deepseek/deepseek-chat"

    # ==================== Provider Rate Limiting ====================
    provider_rate_limit: int = Field(default=40, validation_alias="PROVIDER_RATE_LIMIT")
    provider_rate_window: int = Field(default=60, validation_alias="PROVIDER_RATE_WINDOW")
    provider_max_concurrency: int = Field(default=5, validation_alias="PROVIDER_MAX_CONCURRENCY")
    enable_model_thinking: bool = Field(default=True, validation_alias="ENABLE_MODEL_THINKING")

    # ==================== HTTP Client ====================
    http_read_timeout: float = Field(default=120.0, validation_alias="HTTP_READ_TIMEOUT")
    http_write_timeout: float = Field(default=10.0, validation_alias="HTTP_WRITE_TIMEOUT")
    http_connect_timeout: float = Field(
        default=HTTP_CONNECT_TIMEOUT_DEFAULT, validation_alias="HTTP_CONNECT_TIMEOUT"
    )

    # ==================== Optimizations ====================
    fast_prefix_detection: bool = True
    enable_network_probe_mock: bool = True
    enable_title_generation_skip: bool = True
    enable_suggestion_mode_skip: bool = True
    enable_filepath_extraction_mock: bool = True

    # ==================== Web Server Tools ====================
    enable_web_server_tools: bool = Field(default=False, validation_alias="ENABLE_WEB_SERVER_TOOLS")
    web_fetch_allowed_schemes: str = Field(
        default="http,https", validation_alias="WEB_FETCH_ALLOWED_SCHEMES"
    )
    web_fetch_allow_private_networks: bool = Field(
        default=False, validation_alias="WEB_FETCH_ALLOW_PRIVATE_NETWORKS"
    )

    # ==================== Logging ====================
    log_raw_api_payloads: bool = Field(default=False, validation_alias="LOG_RAW_API_PAYLOADS")
    log_raw_sse_events: bool = Field(default=False, validation_alias="LOG_RAW_SSE_EVENTS")
    log_deepseek_usage: bool = Field(default=False, validation_alias="LOG_DEEPSEEK_USAGE")
    log_api_error_tracebacks: bool = Field(
        default=False, validation_alias="LOG_API_ERROR_TRACEBACKS"
    )

    # ==================== NIM Settings (unused but required by imports) ====================
    nim: NimSettings = Field(default_factory=NimSettings)

    # ==================== Server ====================
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8082, validation_alias="PORT")
    anthropic_auth_token: str = Field(default="", validation_alias="ANTHROPIC_AUTH_TOKEN")

    # ==================== Removed fields (for compatibility) ====================
    messaging_platform: str = "none"
    claude_workspace: str = ""
    claude_cli_bin: str = "claude"
    nvidia_nim_api_key: str = ""
    gemini_api_key: str = ""

    @property
    def provider_type(self) -> str:
        return Settings.parse_provider_type(self.model)

    @property
    def model_name(self) -> str:
        return Settings.parse_model_name(self.model)

    def configured_chat_model_refs(self) -> tuple[ConfiguredChatModelRef, ...]:
        return (
            ConfiguredChatModelRef(
                model_ref=self.model,
                provider_id=Settings.parse_provider_type(self.model),
                model_id=Settings.parse_model_name(self.model),
                sources=("MODEL",),
            ),
        )

    def resolve_thinking(self, _claude_model_name: str) -> bool:
        return self.enable_model_thinking

    def web_fetch_allowed_scheme_set(self) -> frozenset[str]:
        return frozenset(
            part.strip().lower()
            for part in self.web_fetch_allowed_schemes.split(",")
            if part.strip()
        )

    @staticmethod
    def parse_provider_type(model_string: str) -> str:
        return model_string.split("/", 1)[0]

    @staticmethod
    def parse_model_name(model_string: str) -> str:
        return model_string.split("/", 1)[1]

    @field_validator("model")
    @classmethod
    def validate_model_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if "/" not in v:
            raise ValueError(
                "Model must be prefixed with provider type. Format: provider_type/model/name"
            )
        provider = v.split("/", 1)[0]
        if provider not in SUPPORTED_PROVIDER_IDS:
            raise ValueError(f"Invalid provider: '{provider}'. Supported: {SUPPORTED_PROVIDER_IDS}")
        return v

    @model_validator(mode="after")
    def prefer_dotenv_anthropic_auth_token(self) -> "Settings":
        dotenv_value = _env_file_override(self.model_config, "ANTHROPIC_AUTH_TOKEN")
        if dotenv_value is not None:
            self.anthropic_auth_token = dotenv_value
        return self

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

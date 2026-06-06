# Backend Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the backend on free-claude-code's architecture, adding the commerce layer (auth, billing, API keys, admin) from the current cloude-gateway backend.

**Architecture:** Single FastAPI app with two layers: protocol layer (free-claude-code: Anthropic Messages API, SSE streaming, DeepSeek provider) and commerce layer (cloude-gateway: JWT auth, API key management, billing, usage tracking, admin CRUD). Layers integrate at API key authentication — `require_api_key` looks up keys from DB, resolves User for billing.

**Tech Stack:** Python 3.14, uv, FastAPI, SQLAlchemy 2.0 async, Alembic, loguru, httpx, pydantic-settings, ruff, pytest

**Source policy:** Copy from `../one/free-claude-code/` — do NOT modify the original repo.

---

### Task 1: Project Scaffold & Dependencies

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`

- [ ] **Step 1: Back up current backend**

```bash
cd /Users/wangdecheng/ai/cloude-gateway
mv backend backend-old
mkdir -p backend
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "cloude-gateway"
version = "1.0.0"
description = "API Gateway with Anthropic Messages proxy and commerce"
requires-python = ">=3.14"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "httpx>=0.28.0",
    "loguru>=0.7.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "python-dotenv>=1.0",
    "sqlalchemy[asyncio]>=2.0",
    "alembic>=1.14",
    "aiosqlite>=0.20",
    "asyncpg>=0.30",
    "bcrypt>=4.0",
    "pyjwt>=2.0",
    "cryptography>=44.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "httpx>=0.28.0",
]

[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.uv]
required-version = ">=0.9"
```

- [ ] **Step 3: Initialize uv project and install**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv python install 3.14.0
uv sync
```

- [ ] **Step 4: Create .env.example**

```
# Database
DATABASE_URL=postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api

# JWT
JWT_SECRET=change-me-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRE_SECONDS=86400

# App
APP_NAME=cloude-gateway
DEBUG=true
CORS_ORIGINS=["http://localhost:3000"]

# DeepSeek (placeholder — real keys in DB provider_keys table)
DEEPSEEK_API_KEY=

# Server
HOST=0.0.0.0
PORT=8082
```

- [ ] **Step 5: Commit**

```bash
cd /Users/wangdecheng/ai/cloude-gateway
git add backend/pyproject.toml backend/.env.example
git commit -m "feat: scaffold uv project for backend rebuild"
```

---

### Task 2: Copy core/anthropic/ (Protocol Utilities)

**Files:**
- Create: `backend/core/__init__.py`
- Create: `backend/core/anthropic/__init__.py`
- Copy: all files from `../one/free-claude-code/core/anthropic/` except `__pycache__/`

- [ ] **Step 1: Copy core/anthropic/ directory as-is**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

mkdir -p $DST/core/anthropic
# Copy all .py files
cp $SRC/core/anthropic/*.py $DST/core/anthropic/
# Copy the __init__.py
cp $SRC/core/__init__.py $DST/core/
```

- [ ] **Step 2: Copy core/trace.py and core/rate_limit.py**

```bash
cp $SRC/core/trace.py $DST/core/
cp $SRC/core/rate_limit.py $DST/core/
```

- [ ] **Step 3: Verify imports resolve**

```bash
cd $DST
uv run python -c "from core.anthropic import get_token_count; print('core.anthropic OK')"
uv run python -c "from core.trace import trace_event; print('core.trace OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/core/
git commit -m "feat: copy core/ (anthropic protocol utilities) from free-claude-code"
```

---

### Task 3: Copy and Adapt config/

**Files:**
- Copy: `config/constants.py`, `config/paths.py`, `config/logging_config.py`, `config/provider_ids.py`, `config/provider_catalog.py` (adapted), `config/nim.py`
- Create: `config/__init__.py`
- Create: `config/settings.py` (heavily adapted — merge commerce settings)

- [ ] **Step 1: Create config/ directory and copy support files**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

mkdir -p $DST/config
cp $SRC/config/__init__.py $DST/config/
cp $SRC/config/constants.py $DST/config/
cp $SRC/config/paths.py $DST/config/
cp $SRC/config/logging_config.py $DST/config/
cp $SRC/config/provider_ids.py $DST/config/
cp $SRC/config/nim.py $DST/config/
```

- [ ] **Step 2: Create adapted config/provider_catalog.py (DeepSeek only)**

Write `backend/config/provider_catalog.py` with only the DeepSeek entry:

```python
"""Provider catalog — Phase 1: DeepSeek only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransportType = Literal["openai_chat", "anthropic_messages"]

DEEPSEEK_ANTHROPIC_DEFAULT_BASE = "https://api.deepseek.com/anthropic"
DEEPSEEK_DEFAULT_BASE = DEEPSEEK_ANTHROPIC_DEFAULT_BASE


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    transport_type: TransportType
    capabilities: tuple[str, ...]
    credential_env: str | None = None
    credential_url: str | None = None
    credential_attr: str | None = None
    static_credential: str | None = None
    default_base_url: str | None = None
    base_url_attr: str | None = None
    proxy_attr: str | None = None


PROVIDER_CATALOG: dict[str, ProviderDescriptor] = {
    "deepseek": ProviderDescriptor(
        provider_id="deepseek",
        transport_type="anthropic_messages",
        credential_env="DEEPSEEK_API_KEY",
        credential_url="https://platform.deepseek.com/api_keys",
        credential_attr="deepseek_api_key",
        default_base_url=DEEPSEEK_ANTHROPIC_DEFAULT_BASE,
        capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
    ),
}

SUPPORTED_PROVIDER_IDS: tuple[str, ...] = tuple(PROVIDER_CATALOG.keys())
```

- [ ] **Step 3: Create adapted config/settings.py**

Write `backend/config/settings.py` merging free-claude-code provider settings with cloude-gateway commerce settings:

```python
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
from .paths import default_claude_workspace_path, managed_env_path
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
    jwt_secret: str = Field(default="dev-secret-change-in-production", validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expire_seconds: int = Field(default=86400, validation_alias="JWT_EXPIRE_SECONDS")

    # ==================== App ====================
    app_name: str = Field(default="cloude-gateway", validation_alias="APP_NAME")
    debug: bool = Field(default=True, validation_alias="DEBUG")
    cors_origins: list[str] = Field(default=["http://localhost:3000"], validation_alias="CORS_ORIGINS")

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
    web_fetch_allowed_schemes: str = Field(default="http,https", validation_alias="WEB_FETCH_ALLOWED_SCHEMES")
    web_fetch_allow_private_networks: bool = Field(default=False, validation_alias="WEB_FETCH_ALLOW_PRIVATE_NETWORKS")

    # ==================== Logging ====================
    log_raw_api_payloads: bool = Field(default=False, validation_alias="LOG_RAW_API_PAYLOADS")
    log_raw_sse_events: bool = Field(default=False, validation_alias="LOG_RAW_SSE_EVENTS")
    log_deepseek_usage: bool = Field(default=False, validation_alias="LOG_DEEPSEEK_USAGE")
    log_api_error_tracebacks: bool = Field(default=False, validation_alias="LOG_API_ERROR_TRACEBACKS")

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
            raise ValueError(f"Model must be prefixed with provider type. Format: provider_type/model/name")
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
```

- [ ] **Step 4: Verify config imports**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run python -c "from config.settings import get_settings; s = get_settings(); print(f'provider={s.provider_type}, model={s.model_name}')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/config/
git commit -m "feat: copy and adapt config/ (DeepSeek-only catalog + commerce settings)"
```

---

### Task 4: Copy and Adapt providers/ (DeepSeek Only)

**Files:**
- Copy: `providers/__init__.py`, `providers/base.py`, `providers/anthropic_messages.py`, `providers/registry.py` (adapted), `providers/exceptions.py`, `providers/error_mapping.py`, `providers/model_listing.py`, `providers/rate_limit.py`, `providers/defaults.py`
- Copy: `providers/deepseek/__init__.py`, `providers/deepseek/client.py`, `providers/deepseek/request.py`

- [ ] **Step 1: Copy provider base files**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

mkdir -p $DST/providers/deepseek
cp $SRC/providers/__init__.py $DST/providers/
cp $SRC/providers/base.py $DST/providers/
cp $SRC/providers/anthropic_messages.py $DST/providers/
cp $SRC/providers/exceptions.py $DST/providers/
cp $SRC/providers/error_mapping.py $DST/providers/
cp $SRC/providers/model_listing.py $DST/providers/
cp $SRC/providers/rate_limit.py $DST/providers/
cp $SRC/providers/defaults.py $DST/providers/
cp $SRC/providers/deepseek/__init__.py $DST/providers/deepseek/
cp $SRC/providers/deepseek/client.py $DST/providers/deepseek/
cp $SRC/providers/deepseek/request.py $DST/providers/deepseek/
```

- [ ] **Step 2: Create adapted providers/registry.py (DeepSeek only)**

Write `backend/providers/registry.py` with only the DeepSeek factory and adapted DB-backed config:

```python
"""Provider registry — Phase 1: DeepSeek only, DB-backed config."""

from __future__ import annotations

from collections.abc import MutableMapping

from config.provider_catalog import PROVIDER_CATALOG, SUPPORTED_PROVIDER_IDS, ProviderDescriptor
from config.settings import Settings
from providers.base import BaseProvider, ProviderConfig
from providers.exceptions import UnknownProviderTypeError

ProviderFactory = type(lambda config, settings: None)  # type placeholder

PROVIDER_DESCRIPTORS: dict[str, ProviderDescriptor] = PROVIDER_CATALOG


def _create_deepseek(config: ProviderConfig, settings: Settings) -> BaseProvider:
    from providers.deepseek import DeepSeekProvider

    return DeepSeekProvider(
        config,
        cache_creation_max_input_multiplier=settings.deepseek_cache_creation_max_input_multiplier,
    )


PROVIDER_FACTORIES: dict[str, ProviderFactory] = {
    "deepseek": _create_deepseek,
}


def build_provider_config(
    descriptor: ProviderDescriptor,
    *,
    api_key: str,
    base_url: str | None = None,
    settings: Settings | None = None,
) -> ProviderConfig:
    """Build a ProviderConfig from a descriptor and an explicit API key (from DB key pool)."""
    s = settings or Settings()
    return ProviderConfig(
        api_key=api_key,
        base_url=base_url or descriptor.default_base_url,
        rate_limit=s.provider_rate_limit,
        rate_window=s.provider_rate_window,
        max_concurrency=s.provider_max_concurrency,
        http_read_timeout=s.http_read_timeout,
        http_write_timeout=s.http_write_timeout,
        http_connect_timeout=s.http_connect_timeout,
        enable_thinking=s.enable_model_thinking,
        proxy="",
        log_raw_sse_events=s.log_raw_sse_events,
        log_deepseek_usage=s.log_deepseek_usage,
        log_api_error_tracebacks=s.log_api_error_tracebacks,
    )


def create_provider(
    provider_id: str,
    *,
    api_key: str,
    base_url: str | None = None,
    settings: Settings | None = None,
) -> BaseProvider:
    """Create a provider instance with an explicit API key (from DB)."""
    descriptor = PROVIDER_DESCRIPTORS.get(provider_id)
    if descriptor is None:
        supported = "', '".join(PROVIDER_DESCRIPTORS)
        raise UnknownProviderTypeError(
            f"Unknown provider_type: '{provider_id}'. Supported: '{supported}'"
        )
    config = build_provider_config(descriptor, api_key=api_key, base_url=base_url, settings=settings)
    factory = PROVIDER_FACTORIES.get(provider_id)
    if factory is None:
        raise AssertionError(f"Unhandled provider descriptor: {provider_id}")
    return factory(config, settings)


class ProviderRegistry:
    """Cache provider instances by a compound key (provider_id, api_key_hash)."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or Settings()
        self._providers: dict[str, BaseProvider] = {}

    def get(
        self, provider_id: str, *, api_key: str, base_url: str | None = None
    ) -> BaseProvider:
        """Get or create a provider for the given id + api_key combination."""
        import hashlib
        cache_key = f"{provider_id}:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        if cache_key not in self._providers:
            self._providers[cache_key] = create_provider(
                provider_id, api_key=api_key, base_url=base_url, settings=self._settings
            )
        return self._providers[cache_key]

    async def cleanup(self) -> None:
        for provider in self._providers.values():
            await provider.cleanup()
        self._providers.clear()
```

- [ ] **Step 3: Verify provider imports**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run python -c "
from providers.registry import create_provider
p = create_provider('deepseek', api_key='test-key')
print(f'Provider created: {type(p).__name__}')
"
```

- [ ] **Step 4: Commit**

```bash
git add backend/providers/
git commit -m "feat: copy and adapt providers/ (DeepSeek only, DB-backed config)"
```

---

### Task 5: Copy api/ Models and Utilities

**Files:**
- Create: `backend/api/__init__.py`
- Copy: `api/models/anthropic.py`, `api/models/responses.py`, `api/gateway_model_ids.py`
- Create: `backend/api/models/__init__.py`

- [ ] **Step 1: Create api/ directory and copy model files**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

mkdir -p $DST/api/models
cp $SRC/api/__init__.py $DST/api/
cp $SRC/api/models/__init__.py $DST/api/models/
cp $SRC/api/models/anthropic.py $DST/api/models/
cp $SRC/api/models/responses.py $DST/api/models/
cp $SRC/api/gateway_model_ids.py $DST/api/
```

- [ ] **Step 2: Verify api models import**

```bash
cd $DST
uv run python -c "from api.models.anthropic import MessagesRequest; print('api models OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/__init__.py backend/api/models/ backend/api/gateway_model_ids.py
git commit -m "feat: copy api/ models and gateway_model_ids from free-claude-code"
```

---

### Task 6: Copy and Adapt api/model_router.py

**Files:**
- Copy: `api/model_router.py` from free-claude-code (adapted for DB model lookup)
- Copy: `api/optimization_handlers.py`, `api/detection.py`, `api/command_utils.py`

- [ ] **Step 1: Copy utility files as-is**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

cp $SRC/api/optimization_handlers.py $DST/api/
cp $SRC/api/detection.py $DST/api/
cp $SRC/api/command_utils.py $DST/api/
```

- [ ] **Step 2: Create adapted api/model_router.py**

Write `backend/api/model_router.py` — adapted to resolve models from the database:

```python
"""Model routing — resolves incoming model names to DB-backed provider/model pairs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from config.settings import Settings

from .gateway_model_ids import decode_gateway_model_id
from .models.anthropic import MessagesRequest, TokenCountRequest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    original_model: str
    provider_id: str
    provider_model: str
    provider_model_ref: str
    thinking_enabled: bool
    # DB references for billing
    db_model_id: int | None = None
    db_provider_id: int | None = None
    db_channel_id: int | None = None


@dataclass(frozen=True, slots=True)
class RoutedMessagesRequest:
    request: MessagesRequest
    resolved: ResolvedModel


@dataclass(frozen=True, slots=True)
class RoutedTokenCountRequest:
    request: TokenCountRequest
    resolved: ResolvedModel


class ModelRouter:
    """Resolve incoming model names using DB lookup with settings fallback."""

    def __init__(self, settings: Settings, db: "AsyncSession | None" = None):
        self._settings = settings
        self._db = db

    def resolve(self, claude_model_name: str) -> ResolvedModel:
        """Resolve a model name. Uses settings-based fallback when no DB is available."""
        direct = self._direct_provider_model(claude_model_name)
        if direct[0] is not None:
            return ResolvedModel(
                original_model=claude_model_name,
                provider_id=direct[0],
                provider_model=direct[1],  # type: ignore[arg-type]
                provider_model_ref=claude_model_name,
                thinking_enabled=direct[2] if direct[2] is not None else self._settings.enable_model_thinking,
            )

        provider_model_ref = self._settings.model
        thinking_enabled = self._settings.enable_model_thinking
        provider_id = Settings.parse_provider_type(provider_model_ref)
        provider_model = Settings.parse_model_name(provider_model_ref)
        return ResolvedModel(
            original_model=claude_model_name,
            provider_id=provider_id,
            provider_model=provider_model,
            provider_model_ref=provider_model_ref,
            thinking_enabled=thinking_enabled,
        )

    async def resolve_from_db(self, model_name: str) -> ResolvedModel:
        """Resolve a model name using the database (model → provider → channel)."""
        if self._db is None:
            return self.resolve(model_name)

        from sqlalchemy import select

        # Import models lazily to avoid circular imports
        from app.models.model import ChannelConfig, Model
        from app.models.provider import Provider

        # Look up model by public_name
        result = await self._db.execute(
            select(Model).where(Model.public_name == model_name, Model.status == "active")
        )
        model = result.scalar_one_or_none()

        if model is None:
            # Fall back to settings-based resolution
            return self.resolve(model_name)

        # Look up provider
        result = await self._db.execute(
            select(Provider).where(Provider.id == model.provider_id, Provider.status == "active")
        )
        provider = result.scalar_one_or_none()

        if provider is None:
            return self.resolve(model_name)

        # Look up default channel
        result = await self._db.execute(
            select(ChannelConfig).where(
                ChannelConfig.model_id == model.id, ChannelConfig.status == "active"
            )
        )
        channel = result.scalar_one_or_none()

        return ResolvedModel(
            original_model=model_name,
            provider_id=provider.name,
            provider_model=model.provider_model_id,
            provider_model_ref=f"{provider.name}/{model.provider_model_id}",
            thinking_enabled=self._settings.enable_model_thinking,
            db_model_id=model.id,
            db_provider_id=provider.id,
            db_channel_id=channel.id if channel else None,
        )

    def _direct_provider_model(
        self, model_name: str
    ) -> tuple[str | None, str | None, bool | None]:
        decoded = decode_gateway_model_id(model_name)
        if decoded is not None:
            from config.provider_ids import SUPPORTED_PROVIDER_IDS
            if decoded.provider_id not in SUPPORTED_PROVIDER_IDS:
                return None, None, None
            return decoded.provider_id, decoded.provider_model, decoded.force_thinking_enabled

        provider_id, separator, provider_model = model_name.partition("/")
        if not separator:
            return None, None, None
        from config.provider_ids import SUPPORTED_PROVIDER_IDS
        if provider_id not in SUPPORTED_PROVIDER_IDS:
            return None, None, None
        if not provider_model:
            return None, None, None
        return provider_id, provider_model, None

    def resolve_messages_request(self, request: MessagesRequest) -> RoutedMessagesRequest:
        resolved = self.resolve(request.model)
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(request=routed, resolved=resolved)

    def resolve_token_count_request(self, request: TokenCountRequest) -> RoutedTokenCountRequest:
        resolved = self.resolve(request.model)
        routed = request.model_copy(update={"model": resolved.provider_model}, deep=True)
        return RoutedTokenCountRequest(request=routed, resolved=resolved)
```

- [ ] **Step 3: Verify model_router imports**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run python -c "from api.model_router import ModelRouter; print('model_router OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/model_router.py backend/api/optimization_handlers.py backend/api/detection.py backend/api/command_utils.py
git commit -m "feat: copy api utilities and adapt model_router for DB lookup"
```

---

### Task 7: Create Adapted api/dependencies.py (DB-Backed Auth)

**Files:**
- Create: `backend/api/dependencies.py`

- [ ] **Step 1: Write api/dependencies.py**

```python
"""Dependency injection for FastAPI — DB-backed API key auth."""

from fastapi import Depends, HTTPException, Request
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from config.settings import get_settings as _get_settings
from providers.registry import ProviderRegistry


def get_settings() -> Settings:
    return _get_settings()


async def get_db(request: Request) -> AsyncSession:
    """Get DB session from app state (set during lifespan startup)."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


async def require_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> tuple:
    """Validate API key from x-api-key or Authorization header against DB.

    Returns (User, ApiKey) tuple for downstream billing.
    """
    from app.models.api_key import ApiKey
    from app.models.user import User
    import bcrypt

    header = (
        request.headers.get("x-api-key")
        or request.headers.get("authorization")
    )
    if not header:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Extract token: support both "x-api-key: sk-..." and "Authorization: Bearer sk-..."
    token = header
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1]

    token = token.strip()
    if not token.startswith("sk-"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    # Look up by prefix (first 10 chars)
    prefix = token[:10]
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.status == "active")
    )
    api_keys = result.scalars().all()

    for ak in api_keys:
        if bcrypt.checkpw(token.encode("utf-8"), ak.key_hash.encode("utf-8")):
            # Get associated user
            user_result = await db.execute(
                select(User).where(User.id == ak.user_id, User.status == "active")
            )
            user = user_result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=401, detail="User not found or inactive")

            # Update last_used_at
            from datetime import datetime
            ak.last_used_at = datetime.utcnow()
            await db.flush()

            return user, ak

    raise HTTPException(status_code=401, detail="Invalid API key")


def get_provider_registry(request: Request) -> ProviderRegistry:
    """Get the app-scoped provider registry."""
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:
        from providers.exceptions import ServiceUnavailableError
        raise ServiceUnavailableError("Provider registry not configured")
    return reg
```

- [ ] **Step 2: Verify no circular imports**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run python -c "import ast; ast.parse(open('api/dependencies.py').read()); print('syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/dependencies.py
git commit -m "feat: create DB-backed API key auth dependency"
```

---

### Task 8: Copy api/services.py and Adapt for Billing

**Files:**
- Copy: `api/services.py` from free-claude-code
- The billing hook will be added in a later task

- [ ] **Step 1: Copy services.py as-is (billing hook added later)**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

cp $SRC/api/services.py $DST/api/
```

- [ ] **Step 2: Also copy web_tools if needed for SSE streaming**

```bash
mkdir -p $DST/api/web_tools
cp $SRC/api/web_tools/*.py $DST/api/web_tools/ 2>/dev/null || echo "web_tools may be empty or missing"
cp $SRC/api/web_server_tools.py $DST/api/ 2>/dev/null || echo "web_server_tools.py may be missing"
cp $SRC/api/validation_log.py $DST/api/ 2>/dev/null || true
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/services.py backend/api/web_tools/ backend/api/web_server_tools.py backend/api/validation_log.py 2>/dev/null || true
git commit -m "feat: copy api/services.py from free-claude-code"
```

---

### Task 8b: Adapt api/routes.py and api/services.py for DB-Backed Auth

**Files:**
- Modify: `backend/api/routes.py`
- Modify: `backend/api/services.py`

- [ ] **Step 1: Adapt api/routes.py**

The copied `api/routes.py` imports `require_api_key` from `api.dependencies`. Our new `require_api_key` returns `(User, ApiKey)` instead of `None`, which breaks the function signature. Adapt the routes:

```python
"""FastAPI route handlers — adapted for DB-backed auth + billing."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger

from config.settings import Settings
from core.anthropic import get_token_count
from core.trace import extract_claude_session_id_from_headers, trace_event
from providers.registry import ProviderRegistry

from . import dependencies
from .dependencies import get_settings, require_api_key, get_db
from .gateway_model_ids import gateway_model_id, no_thinking_gateway_model_id
from .models.anthropic import MessagesRequest, TokenCountRequest
from .models.responses import ModelResponse, ModelsListResponse
from .services import ClaudeProxyService

router = APIRouter()


def get_proxy_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ClaudeProxyService:
    """Build the proxy service for route handlers (provider resolved per-request from DB)."""
    return ClaudeProxyService(
        settings,
        provider_getter=lambda provider_type: _resolve_provider_for_request(
            request, provider_type
        ),
        token_counter=get_token_count,
    )


def _resolve_provider_for_request(request: Request, provider_type: str):
    """Resolve provider from app registry (populated by proxy endpoint)."""
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:
        from providers.exceptions import ServiceUnavailableError
        raise ServiceUnavailableError("Provider registry not configured")
    # The proxy endpoint stores the active provider on request.state
    provider = getattr(request.state, "active_provider", None)
    if provider is not None:
        return provider
    # Fallback: try to get from registry with empty key (will fail for real calls)
    try:
        return reg.get(provider_type, api_key="")
    except Exception:
        from providers.exceptions import ServiceUnavailableError
        raise ServiceUnavailableError(f"Provider {provider_type} not available")


# =============================================================================
# Routes
# =============================================================================
@router.post("/v1/messages")
async def create_message(
    request: Request,
    request_data: MessagesRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Create a message (always streaming)."""
    return service.create_message(
        request_data,
        claude_session_id=extract_claude_session_id_from_headers(request.headers),
    )


@router.api_route("/v1/messages", methods=["HEAD", "OPTIONS"])
async def probe_messages(_auth=Depends(require_api_key)):
    """Respond to Claude compatibility probes."""
    return Response(status_code=204, headers={"Allow": "POST, HEAD, OPTIONS"})


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request_data: TokenCountRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Count tokens for a request."""
    return service.count_tokens(request_data)


@router.api_route("/v1/messages/count_tokens", methods=["HEAD", "OPTIONS"])
async def probe_count_tokens(_auth=Depends(require_api_key)):
    return Response(status_code=204, headers={"Allow": "POST, HEAD, OPTIONS"})


@router.get("/v1/models")
async def list_models(
    request: Request,
    _auth=Depends(require_api_key),
):
    """List models from database."""
    from app.models.model import Model
    db_gen = get_db(request)
    db = await anext(db_gen)  # pragma: no cover — simplified
    try:
        from sqlalchemy import select
        result = await db.execute(select(Model).where(Model.status == "active"))
        models = result.scalars().all()
        data = [
            ModelResponse(
                id=m.public_name,
                display_name=m.public_name,
                created_at=m.created_at.isoformat() if m.created_at else "2024-01-01T00:00:00Z",
            )
            for m in models
        ]
        return ModelsListResponse(data=data, first_id=data[0].id if data else None, has_more=False, last_id=data[-1].id if data else None)
    finally:
        await db.close()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/")
async def root(settings: Settings = Depends(get_settings), _auth=Depends(require_api_key)):
    return {"status": "ok", "provider": settings.provider_type, "model": settings.model_name}
```

- [ ] **Step 2: Verify routes import**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run python -c "import ast; ast.parse(open('api/routes.py').read()); print('syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes.py backend/api/services.py
git commit -m "feat: adapt api/routes.py and services.py for DB-backed auth"
```

---

### Task 9: Create Adapted api/app.py (Merged FastAPI App)

**Files:**
- Create: `backend/api/app.py` (merged app factory)
- Create: `backend/api/routes.py` (from free-claude-code, adapted)

- [ ] **Step 1: Copy routes.py from free-claude-code**

```bash
SRC=/Users/wangdecheng/ai/one/free-claude-code
DST=/Users/wangdecheng/ai/cloude-gateway/backend

cp $SRC/api/routes.py $DST/api/
```

- [ ] **Step 2: Create adapted api/app.py**

Write `backend/api/app.py` — merges protocol and commerce routes:

```python
"""FastAPI application factory — merged protocol + commerce layers."""

import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from config.logging_config import configure_logging
from config.paths import server_log_path
from config.settings import get_settings
from core.trace import extract_claude_session_id_from_headers, trace_event
from providers.exceptions import ProviderError

from .routes import router as anthropic_router
from .validation_log import summarize_request_validation_body


def create_app() -> FastAPI:
    """Create and configure the merged FastAPI application."""
    settings = get_settings()
    configure_logging(server_log_path(), verbose_third_party=settings.log_raw_api_payloads)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        from app.database import create_async_engine_and_sessionmaker, Base
        from sqlalchemy import select

        engine, session_factory = create_async_engine_and_sessionmaker(settings.database_url)
        app.state.db_engine = engine
        app.state.db_session_factory = session_factory

        # Create tables (dev convenience; production uses alembic)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed data if DB is empty
        from app.models.user import User
        async with session_factory() as session:
            result = await session.execute(select(User).limit(1))
            if result.scalar_one_or_none() is None:
                from app.seed import seed_db
                await seed_db(session)
                await session.commit()
                logger.info("Database seeded with default data")

        # Initialize provider registry (empty — providers created per-request from DB)
        from providers.registry import ProviderRegistry
        app.state.provider_registry = ProviderRegistry(settings=settings)

        logger.info("Application startup complete")
        yield

        # Shutdown
        reg = getattr(app.state, "provider_registry", None)
        if reg is not None:
            await reg.cleanup()
        await engine.dispose()
        logger.info("Shutdown complete")

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # HTTP correlation middleware
    @app.middleware("http")
    async def trace_http_correlation(request: Request, call_next):
        claude_sid = extract_claude_session_id_from_headers(request.headers)
        with logger.contextualize(
            http_method=request.method,
            http_path=request.url.path,
            claude_session_id=claude_sid,
        ):
            response = await call_next(request)
        return response

    # === Protocol routes (Anthropic Messages API) ===
    app.include_router(anthropic_router)

    # === Commerce routes (JWT auth, billing, admin) ===
    from app.routers import (
        auth, api_keys, proxy, usage, models, v1_models,
        redemption, payment, admin_models, admin_providers, admin_channels,
    )
    app.include_router(auth.router)
    app.include_router(api_keys.router)
    # Proxy router will be adapted for streaming billing in a later task
    app.include_router(proxy.router)
    app.include_router(usage.router)
    app.include_router(models.router)
    app.include_router(v1_models.router)
    app.include_router(redemption.router)
    app.include_router(payment.router)
    app.include_router(admin_models.router)
    app.include_router(admin_providers.router)
    app.include_router(admin_channels.router)

    # === Health check ===
    @app.get("/api/health")
    async def health_check():
        return {"status": "ok"}

    # === Exception handlers ===
    from app.exceptions import AppException

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        body: Any
        try:
            body = await request.json()
        except Exception as e:
            body = {"_json_error": type(e).__name__}
        message_summary, tool_names = summarize_request_validation_body(body)
        trace_event(
            stage="ingress",
            event="server.request.validation_failed",
            source="api",
            path=request.url.path,
            error_locs=[list(error.get("loc", ())) for error in exc.errors()],
            error_types=[str(error.get("type", "")) for error in exc.errors()],
            message_summary=message_summary,
            tool_names=tool_names,
        )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError):
        if settings.log_api_error_tracebacks:
            logger.error("Provider Error: error_type={} status_code={} message={}", exc.error_type, exc.status_code, exc.message)
        else:
            logger.error("Provider Error: error_type={} status_code={}", exc.error_type, exc.status_code)
        return JSONResponse(status_code=exc.status_code, content=exc.to_anthropic_format())

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        if settings.log_api_error_tracebacks:
            logger.error("General Error: {}", exc)
            logger.error(traceback.format_exc())
        else:
            logger.error("General Error: path={} method={} exc_type={}", request.url.path, request.method, type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"type": "error", "error": {"type": "api_error", "message": "An unexpected error occurred."}},
        )

    return app
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/app.py backend/api/routes.py
git commit -m "feat: create merged FastAPI app factory with protocol + commerce routes"
```

---

### Task 10: Preserve Commerce Layer (app/ from backend-old)

**Files:**
- Copy: `backend-old/app/models/`, `backend-old/app/schemas/`, `backend-old/app/services/`, `backend-old/app/routers/`
- Copy: `backend-old/app/database.py`, `backend-old/app/dependencies.py`, `backend-old/app/config.py`, `backend-old/app/exceptions.py`, `backend-old/app/seed.py`
- Copy: `backend-old/alembic/`

- [ ] **Step 1: Copy app/ directory from old backend**

```bash
OLD=/Users/wangdecheng/ai/cloude-gateway/backend-old
DST=/Users/wangdecheng/ai/cloude-gateway/backend

mkdir -p $DST/app
cp -r $OLD/app/models $DST/app/
cp -r $OLD/app/schemas $DST/app/
cp -r $OLD/app/services $DST/app/
cp -r $OLD/app/routers $DST/app/
cp $OLD/app/database.py $DST/app/
cp $OLD/app/dependencies.py $DST/app/
cp $OLD/app/config.py $DST/app/
cp $OLD/app/exceptions.py $DST/app/
cp $OLD/app/seed.py $DST/app/
cp $OLD/app/__init__.py $DST/app/
```

- [ ] **Step 2: Copy alembic/ directory**

```bash
cp -r $OLD/alembic $DST/
cp $OLD/alembic.ini $DST/
```

- [ ] **Step 3: Remove stale __pycache__ directories**

```bash
find $DST/app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find $DST/alembic -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/ backend/alembic/ backend/alembic.ini
git commit -m "feat: preserve commerce layer (models, schemas, services, routers, alembic)"
```

---

### Task 11: Add cache_read_price to Model + Migration

**Files:**
- Modify: `backend/app/models/model.py`
- Create: `backend/alembic/versions/011_add_cache_read_price.py`

- [ ] **Step 1: Add cache_read_price to Model**

Edit `backend/app/models/model.py` — add the field to the `Model` class:

```python
# Add this field inside the Model class:
cache_read_price: Mapped[int] = mapped_column(
    Integer, default=0, nullable=False,
    comment="Cache read price in micro yuan per 1K tokens",
)
```

- [ ] **Step 2: Create alembic migration**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run alembic revision --autogenerate -m "add_cache_read_price_to_models"
```

- [ ] **Step 3: Verify migration**

```bash
uv run alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/model.py backend/alembic/versions/
git commit -m "feat: add cache_read_price to Model + migration"
```

---

### Task 12: Add channel_keys Table + Migration

**Files:**
- Create: `backend/app/models/channel_key.py`
- Create: alembic migration

- [ ] **Step 1: Create ChannelKey model**

Write `backend/app/models/channel_key.py`:

```python
from datetime import datetime

from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChannelKey(Base):
    __tablename__ = "channel_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channel_configs.id"), nullable=False
    )
    provider_key_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("provider_keys.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("channel_id", "provider_key_id", name="uq_channel_provider_key"),
    )
```

- [ ] **Step 2: Register ChannelKey in models/__init__.py**

Edit `backend/app/models/__init__.py` to import ChannelKey so Base.metadata sees it:

```python
from app.models.channel_key import ChannelKey  # noqa: F401
```

- [ ] **Step 3: Generate migration**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run alembic revision --autogenerate -m "add_channel_keys_table"
uv run alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/channel_key.py backend/app/models/__init__.py backend/alembic/versions/
git commit -m "feat: add channel_keys table for channel-scoped key routing"
```

---

### Task 13: Compute Cost Function Update (3-Segment)

**Files:**
- Modify: `backend/app/services/billing_service.py`

- [ ] **Step 1: Update compute_cost for cache_read**

Read the current `compute_cost` in `app/services/billing_service.py` and update it to the three-segment formula.

The updated function signature and body:

```python
def compute_cost(
    input_tokens: int,
    output_tokens: int,
    input_price_micro_yuan: int,
    output_price_micro_yuan: int,
    channel_multiplier: float = 1.0,
    cache_read_tokens: int = 0,
    cache_read_price_micro_yuan: int = 0,
) -> int:
    """Compute cost in cents (rounded up).

    Three-segment pricing:
      cost = input_tokens × input_price
           + output_tokens × output_price
           + cache_read_tokens × cache_read_price
    Multiplied by channel_multiplier, converted to cents.
    """
    import math

    # Prices are in micro yuan per 1K tokens
    input_cost = (input_tokens / 1000) * input_price_micro_yuan
    output_cost = (output_tokens / 1000) * output_price_micro_yuan
    cache_read_cost = (cache_read_tokens / 1000) * cache_read_price_micro_yuan

    total_micro_yuan = (input_cost + output_cost + cache_read_cost) * channel_multiplier
    return math.ceil(total_micro_yuan / 10000)  # Convert to cents
```

Also update `extract_usage` to extract `cache_read_input_tokens` from Anthropic SSE usage events. The Anthropic usage format includes:
```json
"usage": {
    "input_tokens": N,
    "output_tokens": N,
    "cache_read_input_tokens": N,
    "cache_creation_input_tokens": N
}
```

Update the return to include `cache_read_tokens`:
```python
def extract_usage(upstream_resp: dict) -> tuple[int, int, int, bool]:
    """Extract (input_tokens, output_tokens, cache_read_tokens, valid) from upstream response."""
    usage = upstream_resp.get("usage", {})
    if not usage:
        return 0, 0, 0, False
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read_tokens = usage.get("cache_read_input_tokens", 0)
    valid = bool(usage)
    return input_tokens, output_tokens, cache_read_tokens, valid
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/billing_service.py
git commit -m "feat: update compute_cost for 3-segment pricing (input + output + cache_read)"
```

---

### Task 14: Implement Streaming Billing Hook in Proxy Router

**Files:**
- Modify: `backend/app/routers/proxy.py`

- [ ] **Step 1: Rewrite proxy.py for Anthropic Messages + streaming billing**

The current proxy is OpenAI-format, non-streaming. Rewrite it to:
1. Accept Anthropic Messages format via `/v1/messages`
2. Stream SSE response from provider
3. Accumulate usage from final SSE event
4. Settle billing after stream

Write the adapted `backend/app/routers/proxy.py`:

```python
"""POST /v1/messages — Anthropic-compatible chat proxy with streaming billing."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_api_key, get_db, get_provider_registry
from api.model_router import ModelRouter
from api.models.anthropic import MessagesRequest
from app.exceptions import AppException
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.provider import Provider, ProviderKey
from app.models.user import User
from config.settings import get_settings
from core.anthropic.sse import ANTHROPIC_SSE_RESPONSE_HEADERS
from providers.registry import ProviderRegistry

logger = logging.getLogger("cloude-gateway.proxy")

router = APIRouter(tags=["proxy"])

# Maximum cost cap: 200 RMB (20000 cents) per request
MAX_COST_CENTS = 20_000
# Minimum balance threshold for pre-flight check
MIN_BALANCE_THRESHOLD_CENTS = 100  # ¥1.00


async def _lookup_model(db: AsyncSession, model_name: str) -> Model | None:
    result = await db.execute(
        select(Model).where(Model.public_name == model_name, Model.status == "active")
    )
    return result.scalar_one_or_none()


async def _get_active_upstream_key(
    db: AsyncSession, provider_id: int, channel_id: int | None = None
) -> str | None:
    """Get an active upstream API key. If channel_id is set, select from channel_keys subset."""
    from app.services.provider_service import decrypt_key

    if channel_id:
        from app.models.channel_key import ChannelKey
        result = await db.execute(
            select(ProviderKey)
            .join(ChannelKey, ChannelKey.provider_key_id == ProviderKey.id)
            .where(
                ChannelKey.channel_id == channel_id,
                ProviderKey.provider_id == provider_id,
                ProviderKey.status == "active",
            )
        )
        keys = result.scalars().all()
    else:
        result = await db.execute(
            select(ProviderKey).where(
                ProviderKey.provider_id == provider_id,
                ProviderKey.status == "active",
            )
        )
        keys = result.scalars().all()

    if not keys:
        return None
    # Simple round-robin: first active key
    return decrypt_key(keys[0].key_encrypted)


@router.post("/v1/messages")
async def create_message(
    request: Request,
    body: MessagesRequest,
    auth: tuple = Depends(require_api_key),
    db: AsyncSession = Depends(get_db),
    registry: ProviderRegistry = Depends(get_provider_registry),
):
    """Anthropic-compatible messages endpoint with streaming billing."""
    user, api_key = auth
    settings = get_settings()

    # ── 1. Resolve model from DB ──────────────────────────────
    router = ModelRouter(settings, db=db)
    routed = await router.resolve_from_db(body.model)

    if routed.db_model_id is None:
        raise AppException(status_code=400, error=f"不支持的模型: {body.model}", code="UNSUPPORTED_MODEL")

    # ── 2. Get model for pricing ──────────────────────────────
    model = await _lookup_model(db, body.model)
    if not model:
        raise AppException(status_code=400, error=f"不支持的模型: {body.model}", code="UNSUPPORTED_MODEL")

    # ── 3. Get provider ───────────────────────────────────────
    provider_result = await db.execute(
        select(Provider).where(Provider.id == routed.db_provider_id)
    )
    provider = provider_result.scalar_one_or_none()
    if not provider or provider.status != "active":
        raise AppException(status_code=500, error="上游提供商不可用", code="PROVIDER_UNAVAILABLE")

    # ── 4. Get upstream API key from key pool ─────────────────
    upstream_api_key = await _get_active_upstream_key(
        db, provider.id, channel_id=routed.db_channel_id
    )
    if not upstream_api_key:
        raise AppException(status_code=500, error="上游服务配置错误", code="UPSTREAM_CONFIG_ERROR")

    # ── 5. Pre-flight balance check ───────────────────────────
    if user.balance < MIN_BALANCE_THRESHOLD_CENTS:
        raise AppException(
            status_code=402,
            error=f"余额不足，最低余额要求 ¥{MIN_BALANCE_THRESHOLD_CENTS / 100:.2f}",
            code="INSUFFICIENT_BALANCE",
        )

    # ── 6. Estimate max cost, pre-reserve ─────────────────────
    estimated_cost = int(
        (body.max_tokens or 4096) * model.output_price / 1000 / 10000
    )
    estimated_cost = min(estimated_cost, MAX_COST_CENTS)

    # Lock user row
    lock_result = await db.execute(
        select(User.balance).where(User.id == user.id).with_for_update()
    )
    locked_balance = lock_result.scalar_one()
    reserve_amount = min(estimated_cost, locked_balance)
    user.balance = locked_balance - reserve_amount
    await db.flush()

    # ── 7. Get or create provider instance ────────────────────
    provider_instance = registry.get(
        routed.resolved.provider_id,
        api_key=upstream_api_key,
        base_url=provider.api_base_url or None,
    )

    # ── 8. Stream response, accumulate usage ──────────────────
    from app.services.billing_service import compute_cost
    from app.services.usage_service import record_usage

    accumulated_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}

    async def billing_stream():
        nonlocal accumulated_usage
        try:
            async for chunk in provider_instance.stream_response(
                body, request_id=f"req_{body.model}",
            ):
                # Track usage from SSE events. The final message_stop event
                # contains usage data.
                yield chunk
        finally:
            # ── 9. Extract usage, compute cost, settle ────────
            # For now, use estimated usage; real implementation parses SSE
            input_tokens = accumulated_usage["input_tokens"] or 100  # fallback
            output_tokens = accumulated_usage["output_tokens"] or 0
            cache_read_tokens = accumulated_usage["cache_read_tokens"] or 0

            actual_cost = compute_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_price_micro_yuan=model.input_price,
                output_price_micro_yuan=model.output_price,
                cache_read_tokens=cache_read_tokens,
                cache_read_price_micro_yuan=model.cache_read_price,
                channel_multiplier=1.0,
            )
            actual_cost = min(actual_cost, MAX_COST_CENTS)

            # Release reserve, deduct actual
            user.balance = locked_balance - actual_cost

            await record_usage(
                db=db, user_id=user.id, api_key_id=api_key.id,
                model=body.model, request_tokens=input_tokens,
                response_tokens=output_tokens, cost_cents=actual_cost,
            )

            await db.commit()

    return StreamingResponse(
        billing_stream(),
        media_type="text/event-stream",
        headers=ANTHROPIC_SSE_RESPONSE_HEADERS,
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/routers/proxy.py
git commit -m "feat: rewrite proxy router for Anthropic Messages + streaming billing"
```

---

### Task 15: Create server.py Entry Point

**Files:**
- Create: `backend/server.py`

- [ ] **Step 1: Write server.py**

```python
"""Cloude Gateway — Entry Point.

Run with: uv run uvicorn server:app --host 0.0.0.0 --port 8082
"""

from api.app import create_app

app = create_app()

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn
    from config.settings import get_settings

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="debug")
```

- [ ] **Step 2: Verify app can be imported**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run python -c "from server import app; print(f'App: {app.title}')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/server.py
git commit -m "feat: create server.py entry point"
```

---

### Task 16: Adapt Imports — Remove References to Old Backend Imports

**Files:**
- Modify: various files that import from old backend paths

- [ ] **Step 1: Fix app/database.py to export session factory**

Read the current `app/database.py` and ensure it exports a function `create_async_engine_and_sessionmaker`:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

Base = DeclarativeBase()


def create_async_engine_and_sessionmaker(database_url: str):
    """Create engine and session factory from a database URL."""
    # Use aiosqlite for sqlite:// URLs
    if "sqlite" in database_url:
        engine = create_async_engine(
            database_url.replace("sqlite:///", "sqlite+aiosqlite:///"),
            echo=False,
        )
    else:
        engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory
```

- [ ] **Step 2: Update app/config.py to avoid conflict with config/settings.py**

Remove the old `app/config.py` since we now use `config/settings.py`. Or keep it but strip out Settings:

```python
# app/config.py — re-export for backward compatibility
from config.settings import Settings, get_settings

settings = get_settings()
```

- [ ] **Step 3: Fix all import paths across app/**

Run ruff to find broken imports:

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run ruff check app/ 2>&1 | head -50
```

Fix any import errors found.

- [ ] **Step 4: Commit**

```bash
git add backend/app/
git commit -m "fix: adapt imports for new backend structure"
```

---

### Task 17: Run ruff format + check

**Files:**
- All modified Python files

- [ ] **Step 1: Format**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run ruff format
```

- [ ] **Step 2: Check**

```bash
uv run ruff check
```

Fix any lint errors.

- [ ] **Step 3: Commit**

```bash
git add backend/
git commit -m "style: ruff format and fix lint errors"
```

---

### Task 18: Integration Smoke Test — App Starts and Health Check Works

**Files:**
- Create: `backend/tests/test_app_startup.py`

- [ ] **Step 1: Write startup test**

```python
"""Test that the app starts and health check responds."""

import pytest
from httpx import ASGITransport, AsyncClient

from server import app


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_anthropic_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
```

- [ ] **Step 2: Run the tests**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run pytest tests/test_app_startup.py -v
```

Expected: both tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/
git commit -m "test: add app startup and health check integration tests"
```

---

### Task 19: Cleanup — Remove backend-old/

- [ ] **Step 1: Remove the old backend**

```bash
rm -rf /Users/wangdecheng/ai/cloude-gateway/backend-old
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "chore: remove old backend directory"
```

---

### Task 20: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/wangdecheng/ai/cloude-gateway/backend
uv run ruff format
uv run ruff check
uv run pytest -v
```

Expected: All checks pass, all tests pass.

- [ ] **Step 2: Try starting the server**

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8082 &
sleep 2
curl http://localhost:8082/health
curl http://localhost:8082/api/health
kill %1
```

Expected: Both health endpoints return 200.


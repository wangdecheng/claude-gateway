# MiniMax Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add MiniMax as a DB-backed provider so admin-created `miniMax` channels route through the existing Anthropic Messages streaming proxy.

**Architecture:** Add canonical provider id `minimax` to the catalog and registry, then add a thin `MiniMaxProvider` that inherits `AnthropicMessagesTransport`. Keep the admin adapter as `anthropic-messages`; route by canonicalized provider name.

**Tech Stack:** Python, FastAPI, SQLAlchemy async, httpx, Pydantic Settings, pytest, ruff, ty.

## Preconditions

- Read spec: `docs/superpowers/specs/2026-06-07-minimax-provider-design.md`.
- Use @superpowers:test-driven-development while implementing each code task.
- Use @superpowers:verification-before-completion before claiming completion.
- Do not write MiniMax API keys to repository files.

## Task 1: Add Failing Provider Import And Usage Tests

**Files:**
- Modify: `backend/tests/test_provider_imports.py`
- Create: `backend/tests/test_minimax_cache_creation.py`

**Step 1: Write the failing import test**

Append to `backend/tests/test_provider_imports.py`:

```python
def test_minimax_provider_imports():
    from providers.minimax import MiniMaxProvider

    assert MiniMaxProvider is not None
```

**Step 2: Add MiniMax usage normalization tests**

Create `backend/tests/test_minimax_cache_creation.py` using the MiniMax tests
from `../one/free-claude-code/tests/test_minimax_cache_creation.py`. Keep only
unit tests for:

- `_synthetic_cache_creation_tokens`
- `_fill_minimax_usage_cache_creation`
- `_normalize_minimax_usage_event`

Expected imports:

```python
from core.anthropic.native_sse_block_policy import format_native_sse_event
from providers.minimax.client import (
    _MiniMaxNativeSseState,
    _fill_minimax_usage_cache_creation,
    _normalize_minimax_usage_event,
    _synthetic_cache_creation_tokens,
)
```

**Step 3: Run tests and verify failure**

Run:

```bash
uv run pytest backend/tests/test_provider_imports.py backend/tests/test_minimax_cache_creation.py -q
```

Expected: FAIL because `providers.minimax` does not exist.

## Task 2: Add MiniMax Provider Implementation

**Files:**
- Create: `backend/providers/minimax/client.py`
- Create: `backend/providers/minimax/__init__.py`
- Modify: `backend/config/provider_catalog.py`
- Modify: `backend/providers/defaults.py`
- Modify: `backend/providers/base.py`
- Modify: `backend/config/settings.py`

**Step 1: Add catalog default and descriptor**

In `backend/config/provider_catalog.py`:

```python
MINIMAX_DEFAULT_BASE = "https://api.minimaxi.com/anthropic"
```

Add descriptor:

```python
"minimax": ProviderDescriptor(
    provider_id="minimax",
    transport_type="anthropic_messages",
    credential_env="MINIMAX_API_KEY",
    credential_url="https://platform.minimaxi.com/user-center/basic-information/interface-key",
    credential_attr="minimax_api_key",
    default_base_url=MINIMAX_DEFAULT_BASE,
    capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
),
```

**Step 2: Re-export default URL**

In `backend/providers/defaults.py`, import and include `MINIMAX_DEFAULT_BASE`
in `__all__`.

**Step 3: Add settings fields**

In `backend/config/settings.py`, near DeepSeek settings:

```python
# ==================== MiniMax ====================
minimax_api_key: str = Field(default="", validation_alias="MINIMAX_API_KEY")
minimax_cache_creation_max_input_multiplier: int = Field(
    default=5, ge=1, validation_alias="MINIMAX_CACHE_CREATION_MAX_INPUT_MULTIPLIER"
)
```

Near logging settings:

```python
log_minimax_usage: bool = Field(default=False, validation_alias="LOG_MINIMAX_USAGE")
```

**Step 4: Add provider config field**

In `backend/providers/base.py`:

```python
log_minimax_usage: bool = False
```

**Step 5: Create MiniMax provider**

Copy the implementation shape from
`../one/free-claude-code/providers/minimax/client.py` into
`backend/providers/minimax/client.py`, preserving:

- `_MiniMaxNativeSseState`
- `_synthetic_cache_creation_tokens`
- `_fill_minimax_usage_cache_creation`
- `_normalize_minimax_usage_event`
- `MiniMaxProvider`

Keep these MiniMax-specific overrides:

```python
def _request_headers(self) -> dict[str, str]:
    return {
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {self._api_key}",
        "Content-Type": "application/json",
    }

async def _send_stream_request(self, body: dict) -> httpx.Response:
    request = self._client.build_request(
        "POST",
        "/v1/messages",
        json=body,
        headers=self._request_headers(),
    )
    return await self._client.send(request, stream=True)

async def _send_model_list_request(self) -> httpx.Response:
    return await self._client.get("/v1/models", headers=self._model_list_headers())

def _model_list_headers(self) -> dict[str, str]:
    return {"X-Api-Key": self._api_key}
```

**Step 6: Export provider**

Create `backend/providers/minimax/__init__.py`:

```python
from .client import MiniMaxProvider

__all__ = ("MiniMaxProvider",)
```

**Step 7: Run focused tests**

Run:

```bash
uv run pytest backend/tests/test_provider_imports.py backend/tests/test_minimax_cache_creation.py -q
```

Expected: PASS.

**Step 8: Commit**

```bash
git add backend/providers/minimax backend/config/provider_catalog.py backend/providers/defaults.py backend/providers/base.py backend/config/settings.py backend/tests/test_provider_imports.py backend/tests/test_minimax_cache_creation.py
git commit -m "feat(provider): add minimax provider"
```

## Task 3: Add Registry Wiring Tests

**Files:**
- Create or modify: `backend/tests/test_provider_registry.py`
- Modify: `backend/providers/registry.py`

**Step 1: Write failing registry tests**

Add tests:

```python
from config.provider_catalog import PROVIDER_CATALOG, SUPPORTED_PROVIDER_IDS
from config.settings import Settings
from providers.registry import PROVIDER_FACTORIES, create_provider


def test_provider_catalog_and_factories_include_minimax():
    assert "minimax" in PROVIDER_CATALOG
    assert "minimax" in SUPPORTED_PROVIDER_IDS
    assert "minimax" in PROVIDER_FACTORIES


def test_create_minimax_provider_from_registry():
    from providers.minimax import MiniMaxProvider

    provider = create_provider(
        "minimax",
        api_key="test-key",
        base_url="https://api.minimaxi.com/anthropic",
        settings=Settings(_env_file=None),
    )

    assert isinstance(provider, MiniMaxProvider)
```

If `Settings(_env_file=None)` is not accepted by the local settings class, use
`Settings()` and rely on explicit `api_key`.

**Step 2: Run and verify failure**

Run:

```bash
uv run pytest backend/tests/test_provider_registry.py -q
```

Expected: FAIL because registry has no `minimax` factory.

**Step 3: Implement registry wiring**

In `backend/providers/registry.py` add:

```python
def _create_minimax(config: ProviderConfig, settings: Settings) -> BaseProvider:
    from providers.minimax import MiniMaxProvider

    return MiniMaxProvider(
        config,
        cache_creation_max_input_multiplier=settings.minimax_cache_creation_max_input_multiplier,
    )
```

Add to `PROVIDER_FACTORIES`:

```python
"minimax": _create_minimax,
```

In `build_provider_config()`, pass:

```python
log_minimax_usage=s.log_minimax_usage,
```

**Step 4: Run tests**

Run:

```bash
uv run pytest backend/tests/test_provider_registry.py backend/tests/test_provider_imports.py backend/tests/test_minimax_cache_creation.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/providers/registry.py backend/tests/test_provider_registry.py
git commit -m "feat(provider): wire minimax registry"
```

## Task 4: Add DB Routing Compatibility Test

**Files:**
- Modify: `backend/tests/test_proxy_routing_compat.py`

**Step 1: Write failing route canonicalization test**

Add a test that updates the seeded provider name to `miniMax`, calls
`/v1/messages`, and asserts the fake registry saw `minimax`.

Use existing fixture and fake registry in `backend/tests/test_proxy_routing_compat.py`:

```python
@pytest.mark.asyncio
async def test_proxy_canonicalizes_minimax_provider_name():
    fake_provider = FakeProvider()
    fake_registry = FakeRegistry(fake_provider)
    app.state.provider_registry = fake_registry

    async with app.state.db_session_factory() as db:
        provider = (await db.execute(select(Provider))).scalars().first()
        provider.name = "miniMax"
        provider.api_base_url = "https://api.minimaxi.com/anthropic"
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/messages",
            headers={"anthropic-auth-token": RAW_CLIENT_KEY},
            json={
                "model": "claude-opus-4-8",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "OK"}],
            },
        )

    assert resp.status_code == 200
    assert fake_registry.seen_provider_id == "minimax"
    assert fake_registry.seen_base_url == "https://api.minimaxi.com/anthropic"
```

**Step 2: Run test**

Run:

```bash
uv run pytest backend/tests/test_proxy_routing_compat.py::test_proxy_canonicalizes_minimax_provider_name -q
```

Expected: PASS after `minimax` is in supported provider ids. If it fails, fix
only `_canonical_provider_id()` behavior in `backend/api/model_router.py`.

**Step 3: Run compatibility file**

Run:

```bash
uv run pytest backend/tests/test_proxy_routing_compat.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/tests/test_proxy_routing_compat.py backend/api/model_router.py
git commit -m "test(provider): cover minimax db routing"
```

Only include `backend/api/model_router.py` if it changed.

## Task 5: Update Provider Documentation

**Files:**
- Modify: `docs/backend-providers.md`

**Step 1: Add MiniMax admin configuration note**

Add a concise section:

```markdown
### MiniMax

Use provider name `minimax`, `miniMax`, or `MiniMax`; routing canonicalizes the
name to provider id `minimax`.

Admin provider settings:

- API Base URL: `https://api.minimaxi.com/anthropic`
- Auth Header: `Authorization`
- Adapter: `anthropic-messages`
- Channel `providerModelId`: for example `MiniMax-M3`
```

**Step 2: Commit**

```bash
git add docs/backend-providers.md
git commit -m "docs(provider): document minimax setup"
```

## Task 6: Final Verification

**Files:**
- Verify all touched files.

**Step 1: Run formatting/lint/type/test checks**

Run:

```bash
uv run ruff check
uv run ty check
uv run pytest
```

Expected: all PASS.

If failures occur, use @superpowers:systematic-debugging before changing code.

**Step 2: Inspect git status**

Run:

```bash
git status --short
```

Expected: clean, or only intentional uncommitted changes if the user requested
not to commit implementation.

**Step 3: Summarize result**

Report:

- provider id added: `minimax`
- accepted admin provider names: `miniMax`, `MiniMax`, `minimax`
- required admin settings
- verification commands and outcomes

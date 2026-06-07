# MiniMax Provider Design

## Objective

Add MiniMax as a first-class backend provider for DB-backed channels. An admin
can create a provider named `miniMax`, `MiniMax`, or `minimax`, attach keys, and
route a channel such as `MiniMax-M3` through the existing `/v1/messages`
streaming proxy.

The implementation should follow the existing DeepSeek provider pattern and
reuse the MiniMax provider behavior from `../one/free-claude-code`.

## Chosen Approach

Use canonical provider id `minimax` and keep the existing
`anthropic-messages` adapter value.

The provider display name remains flexible. Routing already normalizes
`Provider.name.strip().lower()` and checks it against supported provider ids, so
adding `minimax` to `SUPPORTED_PROVIDER_IDS` lets `miniMax`, `MiniMax`, and
`minimax` resolve to the same runtime provider id.

No MiniMax-specific adapter string is needed. A dedicated adapter value would
increase schema, UI, and compatibility surface without changing the runtime
transport.

## Architecture

Add `minimax` to `backend/config/provider_catalog.py` with:

- transport type: `anthropic_messages`
- default base URL: `https://api.minimaxi.com/anthropic`
- credential env metadata: `MINIMAX_API_KEY`
- capabilities: `chat`, `streaming`, `tools`, `thinking`, `native_anthropic`

Add `backend/providers/minimax/`:

- `client.py` defines `MiniMaxProvider`.
- `__init__.py` exports `MiniMaxProvider`.

`MiniMaxProvider` inherits `AnthropicMessagesTransport`. It differs from
DeepSeek in endpoint paths and auth headers:

- messages: `POST /v1/messages`
- model list: `GET /v1/models`
- messages auth: `Authorization: Bearer <key>`
- model-list auth: `X-Api-Key: <key>`

The provider will include the MiniMax usage normalization from
`../one/free-claude-code/providers/minimax/client.py`, because MiniMax may report
`cache_read_input_tokens` while omitting `cache_creation_input_tokens`. The
gateway billing path already reads those cache fields from normalized SSE
events.

## Components

Backend runtime:

- `backend/providers/minimax/client.py`: MiniMax transport implementation.
- `backend/providers/minimax/__init__.py`: public provider export.
- `backend/providers/defaults.py`: re-export `MINIMAX_DEFAULT_BASE`.
- `backend/providers/registry.py`: add `_create_minimax()` and
  `PROVIDER_FACTORIES["minimax"]`.
- `backend/providers/base.py`: add `log_minimax_usage` to `ProviderConfig`.
- `backend/config/settings.py`: add
  `minimax_cache_creation_max_input_multiplier` and `log_minimax_usage`.
- `backend/config/provider_catalog.py`: add catalog entry and default URL.

Admin/backend configuration:

- Keep provider schema adapter choices as
  `openai-chat-completions | anthropic-messages`.
- Keep frontend provider form adapter choices unchanged.
- Document that MiniMax should be configured with `anthropic-messages`,
  `Authorization`, and base URL `https://api.minimaxi.com/anthropic`.

## Data Flow

1. Admin creates a provider named `miniMax` or equivalent casing.
2. Admin adds one or more encrypted MiniMax upstream keys.
3. Admin creates a channel from a public model to that provider with
   `providerModelId`, for example `MiniMax-M3`.
4. `/v1/messages` resolves the public model through DB channel routing.
5. `ModelRouter` canonicalizes the provider name to `minimax`.
6. `ProviderRegistry.get("minimax", api_key=..., base_url=...)` creates or
   reuses `MiniMaxProvider`.
7. `MiniMaxProvider` streams to
   `https://api.minimaxi.com/anthropic/v1/messages`.
8. SSE usage fields are normalized before billing parses cache and token usage.

## Error Handling

Use existing shared transport behavior:

- unknown provider ids still raise `UnknownProviderTypeError`;
- non-2xx MiniMax responses use shared safe HTTP error logging and mapping;
- malformed model-list responses raise `ModelListResponseError`;
- missing DB provider keys continue to return the existing upstream config error.

No MiniMax-specific exception mapping is required unless tests or live behavior
show a stable error shape that improves diagnostics.

## Testing

Add focused tests:

- MiniMax provider imports under the runtime Python version.
- MiniMax usage cache normalization matches the migrated behavior.
- Registry/catalog supported ids and factories include `minimax`.
- `create_provider("minimax", ...)` returns `MiniMaxProvider`.
- DB proxy routing with `Provider.name="miniMax"` calls
  `registry.get("minimax", ...)`.

Run verification:

- `uv run ruff check`
- `uv run ty check`
- `uv run pytest`

Live MiniMax API testing is out of scope for this change unless an API key is
provided through the environment. No upstream API key should be written to repo
files.

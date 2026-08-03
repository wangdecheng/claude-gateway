# Architecture Overview

## System Diagram

```
                          ┌─────────────────────────────────────┐
                          │          External Clients           │
                          │  (Claude Code, API consumers,       │
                          │   browser-based admin UI)           │
                          └───┬──────────────┬─────────────────┘
                              │              │
                    /v1/messages, /v1/models   /api/auth, /api/* (commerce)
                              │              │
                              ▼              ▼
┌─────────────────────┐      ┌──────────────────────────────┐
│    Next.js 3000     │      │     FastAPI Backend 8082      │
│                     │      │                              │
│  /api/* ──proxy──>  │──────│> /api/*    Commerce routes   │
│  /(auth)/*          │      │  /v1/*     Anthropic routes  │
│  /(user)/*          │      │  /admin/*  Admin routes       │
│  /admin/*           │      │                              │
└─────────────────────┘      └──────────┬───────────────────┘
                                        │
                    ┌───────────────────┴──────────────────┐
                    │       providers/ (plugin layer)      │
                    │  DeepSeekProvider / GlmProvider /     │
                    │  MiniMaxProvider / VolcengineProvider │
                    │  (all via AnthropicMessagesTransport) │
                    └───────────────────┬──────────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┬─────────────────────────┐
              ▼                         ▼                         ▼                         ▼
     api.deepseek.com/anthropic  api.minimaxi.com/anthropic   cn.morbuke.com       ark.cn-beijing.volces.com
                                                                                            /anthropic
                                                        │
                                          pending_billings (queue)
                                                        │
                                          BillingWorker (async, every 30s)
                                                        ▼
                                          RequestLog + BillingRecord
                                          + UsageRecord (settle)
```

## Module Map

```
backend/
├── server.py                    # Entry point: uv run uvicorn server:app
├── api/                         # Anthropic-compatible API layer + app factory
│   ├── app.py                   # create_app() + lifespan (THE active app)
│   ├── routes.py                # Anthropic Messages API routes (non-billing)
│   ├── services.py              # Anthropic protocol handlers
│   ├── model_router.py          # Model->Provider resolution (DB-backed)
│   ├── dependencies.py          # get_db, get_provider_registry, require_api_key
│   ├── validation_log.py        # Request validation error logging
│   ├── admin_*.py               # Admin config / routes / urls / static (lifespan helpers)
│   ├── detection.py / command_utils.py / gateway_model_ids.py
│   │                            # Misc helpers (admin detection, model id resolution)
│   ├── optimization_handlers.py # Optimization-related endpoints
│   ├── web_server_tools.py / web_tools/  # Server-side web tooling
│   └── models/                  # Pydantic protocol primitives (anthropic/)
├── app/                         # Commerce layer
│   ├── database.py              # Base, engine/session factory
│   ├── dependencies.py          # JWT auth dependency (cookie), admin check
│   ├── exceptions.py            # AppException
│   ├── seed.py                  # Idempotent seed data
│   ├── models/                  # SQLAlchemy ORM models (see Data Model)
│   ├── routers/                 # FastAPI route modules (proxy, auth, keys, admin_*)
│   ├── schemas/                 # Pydantic request/response models
│   └── services/
│       ├── billing/             # *** active async billing pipeline ***
│       │   ├── compute.py       # compute_cost() + compute_costs_for_pending()
│       │   ├── pending.py       # write_pending_billing(), claim_pending_batch()
│       │   ├── settle.py        # settle_one(), mark_retry(), max_retry_reached()
│       │   ├── worker.py        # BillingWorker (asyncio task, FOR UPDATE SKIP LOCKED)
│       │   └── token_coefficient.py  # apply_coefficient() (discount on tokens)
│       ├── streaming/sse_rewrite.py  # in-flight SSE model-name remap + coefficient
│       ├── auth_service.py / api_key_service.py / provider_service.py
│       ├── channel_service.py / model_service.py / payment_service.py
│       ├── redemption_service.py / usage_service.py
│       ├── token_coefficient_service.py  # global + per-model discount config
│       └── upstream_client.py   # (legacy reference)
│   └── billing_service.py      # *** LEGACY: synchronous billing, DO NOT use ***
│                                # active path is services/billing/. Still imports
│                                # the retired ChannelConfig; kept for reference.
├── config/                      # Centralized configuration
│   ├── settings.py              # Pydantic Settings (all env vars)
│   ├── logging_config.py        # Loguru structured logging
│   ├── paths.py                 # ~/.fcc/ paths
│   ├── provider_catalog.py       # ProviderDescriptor registry (deepseek/glm/minimax)
│   ├── provider_ids.py           # SUPPORTED_PROVIDER_IDS
│   ├── constants.py              # Shared defaults
│   └── nim.py                   # NVIDIA NIM params (unused)
├── providers/                   # Pluggable AI provider abstraction
│   ├── base.py                  # BaseProvider ABC + ProviderConfig
│   ├── registry.py              # ProviderRegistry (factory + instance cache)
│   ├── anthropic_messages.py    # SSE streaming transport (AnthropicMessagesTransport)
│   ├── rate_limit.py            # GlobalRateLimiter
│   ├── error_mapping.py         # Exception -> ProviderError mapping
│   ├── exceptions.py            # ProviderError hierarchy
│   ├── defaults.py / model_listing.py
│   ├── deepseek/                # DeepSeek adapter (api.deepseek.com/anthropic)
│   ├── glm/                     # GLM adapter (cn.morbuke.com)
│   ├── minimax/                 # MiniMax adapter (api.minimaxi.com/anthropic)
│   └── volcengine/              # Volcengine adapter (ark.cn-beijing.volces.com/anthropic)
├── core/                        # Low-level protocol primitives
│   ├── trace.py                 # Request tracing with session ID
│   ├── rate_limiting.py         # Rate limit token bucket
│   └── anthropic/               # SSE, conversion, thinking, tokens, tools, ...
├── alembic/                     # Database migrations
│   ├── env.py
│   └── versions/
└── tests/                       # Backend tests (SQLite in-memory)

frontend/
├── middleware.ts                # JWT verification + route gating (injects X-User-ID/Role)
├── next.config.ts               # Proxy /api/* -> localhost:8082
├── app/
│   ├── layout.tsx               # Root layout (Providers wrapper)
│   ├── (auth)/                  # Public: login, register, forgot/reset password
│   ├── (user)/                  # Authenticated: dashboard, models, keys, usage,
│   │   └── layout.tsx           #   recharge, redeem, settings  (nav bar + balance)
│   └── admin/                   # Admin CRUD: models, channels, providers,
│       └── layout.tsx           #   redemption, users, discounts (sidebar + role check)
├── components/
│   ├── Providers.tsx            # TanStack Query + Auth context
│   ├── ui/                      # shadcn/ui primitives
│   ├── forms/                   # Form components (react-hook-form + zod)
│   └── data/                    # BalanceDisplay, KeyList, ModelCard, ChannelExplorer
├── lib/
│   ├── api/client.ts            # Generic fetch wrapper (credentials: "include")
│   ├── api/*.ts                 # Domain TanStack Query hooks + admin/*
│   ├── auth/AuthContext.tsx     # Auth state management
│   └── utils/                   # cn(), formatPrice(), maskSK()
└── tests/                       # Frontend tests (Vitest + Testing Library)
```

## Data Model

Core entity chain (route resolution + key pool):

```
User ──< ApiKey (channel_id ──► Provider.id)
                                    │
Model ──< ModelProviderRoute (table: model_providers) ──► Provider
              │  provider_model, is_default, status
              │
         Provider ──< ProviderKey  (AES-256-GCM encrypted, status active|revoked)
              │              │
              └─< ChannelKey ──┘   (optional subset of ProviderKey for a channel)
```

Billing/audit tables (written by the async pipeline):

| Table | Purpose | Key constraints |
|-------|---------|-----------------|
| `pending_billings` | Async billing queue between proxy and worker | `request_id` UNIQUE (idempotency); `status` pending\|settled\|dead; `retry_count`; `upstream_message_id` indexed |
| `request_logs` | Per-call record (settled) | `request_id` from pending |
| `billing_records` | Append-only deduction ledger | `request_log_id` UNIQUE (anti-double-charge); append-only |
| `usage_records` | Per-user usage history (settled) | denormalized `model` = public_name |
| `payment_records` | Recharge / payment | `transaction_id` UNIQUE (idempotency) |
| `token_coefficient_configs` | Discount coefficients (global + per-model) | loaded into `TokenCoefficientService` at startup |

> Naming note: the frontend/API surface still calls `ModelProviderRoute` a **"channel"** (`/api/admin/channels`) for backward compatibility, but the underlying table is `model_providers` (a model↔provider binding with `provider_model` + `is_default`). `Provider.channel_name` + `Provider.multiplier` carry the old channel-level display/pricing.

## Data Flow: API Proxy Request (async billing)

```
Client sends POST /v1/messages
  │
  ▼
[Next.js proxy] ──rewrite──> [FastAPI proxy.py::create_message]
                                    │
                  ── synchronous (request transaction) ──────────────
                  1. Auth: require_api_key -> (User, ApiKey)
                  2. Resolve: ModelRouter.resolve_from_db() or
                     resolve_with_channel(model, api_key.channel_id)
                     -> ResolvedModel(db_model_id, db_provider_id,
                                      db_route_id, provider_model)
                  3. Pricing: lookup Model; TokenCoefficientService
                     .get_for_model(model.id) -> coefficient (discount)
                  4. Provider: SELECT Provider WHERE id=resolved.db_provider_id
                     (status must be 'active')
                  5. Key pool: _get_active_upstream_key(provider_id, channel_id)
                     -> channel_keys subset if bound, else all active ProviderKey
                     -> decrypt AES-256-GCM (provider_id as AAD)
                  6. Pre-flight: user.balance >= 10 cents (¥0.10)  [no reservation]
                  7. Provider instance: registry.get(provider_id, api_key, base_url)
                     cached by (provider_id, sha256(api_key)[:16])
                  8. db.commit()  <-- release request transaction before streaming
                  ──────────────────────────────────────────────────
                                    │
                  ── streaming (billing_stream generator) ─────────
                  9. provider_instance.stream_response() -> SSE chunks
                     - parse usage from message_start / message_delta
                       (input / output / cache_read / cache_creation)
                     - capture upstream message.id from message_start
                     - IN-FLIGHT REWRITE of each chunk:
                       a. provider_model -> original Claude model name
                       b. apply token coefficient (discount) to usage
                  10. finally (own transaction):
                     - apply_coefficient() to accumulated usage
                     - write_pending_billing(...)  [request_id UNIQUE]
                     - db.commit()
                  ──────────────────────────────────────────────────
                                    │
                  ── async settlement (BillingWorker, every 30s) ───
                  11. claim_pending_batch(): SELECT ... FOR UPDATE
                      SKIP LOCKED where status='pending' AND
                      created_at < now-5s (skip rows still being written)
                  12. settle_one() per row (own short transaction):
                      - compute_costs_for_pending() -> cost in cents
                      - SELECT user FOR UPDATE -> balance -= cost
                      - INSERT request_log, billing_record, usage_record
                      - mark pending status='settled'
                  13. on failure: mark_retry(); after 3 retries -> 'dead'
                  ──────────────────────────────────────────────────
```

### Cost formula (`billing/compute.py`)

Prices stored in **micro-yuan per 1K tokens**; result in **cents (分)**, rounded up.

```
effective_input = input_tokens + cache_creation_tokens + cache_read_tokens / 10
base_micro_yuan = (effective_input / 1000 × input_price
                 + output_tokens / 1000 × output_price)
cost_cents      = ceil(base_micro_yuan × provider.multiplier / 10_000)
```

- `cache_creation` charged at **full input rate**
- `cache_read` charged at **1/10 input rate** (10% / 1折)
- `provider.multiplier` is the channel-level pricing multiplier

### SSE in-flight rewrite (`streaming/sse_rewrite.py`)

Each SSE chunk is rewritten before being forwarded to the client:
1. **Model-name remap**: upstream may write its own model id (e.g. `astron-code-latest`) into `message_start`; rewrite it back to the user's original Claude model name so the client sees what it asked for.
2. **Token coefficient**: apply the per-model discount coefficient to the usage fields in SSE events, so usage reported to the client matches what is billed.

## Key Design Decisions

1. **Dual auth system**: JWT cookies (RS256) for the commerce UI, API keys (`sk-...` Bearer) for the proxy. Separate dependency chains, shared `User` model. Frontend middleware verifies JWT with `jose` and injects `X-User-ID`/`X-User-Role` headers.

2. **Async billing (pending + worker), NOT pre-reserve**: The request path does **no balance reservation** — only a ¥0.10 pre-flight check. After streaming, a `pending_billings` row is written; a background `BillingWorker` (in-process asyncio task, scans every 30s) settles each row in its own short transaction. This decouples streaming latency from settlement and gives a retry/dead-letter path. Multi-worker safety via `FOR UPDATE SKIP LOCKED`. `pending_billings.request_id` UNIQUE + `billing_records.request_log_id` UNIQUE together prevent double-charging. The worker only claims rows older than 5s to avoid racing an in-flight `finally` write.

3. **Provider plugin system**: `BaseProvider` ABC with `stream_response()`, `list_model_ids()`, `preflight_stream()`, `cleanup()`. Factory registry keyed by `provider_id` (`deepseek` / `glm` / `minimax` / `volcengine`), instances cached by `(provider_id, sha256(api_key)[:16])`. All four providers use the `anthropic_messages` transport. New providers added by implementing the ABC + registering a factory + a `ProviderDescriptor` in `config/provider_catalog.py`.

4. **Token coefficient (discount) layer**: `TokenCoefficientService` loads global + per-model coefficients at startup and applies them both at billing time (`apply_coefficient`) and in-flight on the SSE stream, so client-reported usage matches billed usage.

5. **Configuration cascade**: `.env` (project) -> `~/.fcc/.env` (managed) -> `$FCC_ENV_FILE` (explicit). Pydantic Settings reads all of them.

6. **Database auto-create**: Tables created in lifespan if missing. Alembic for production schema changes. Seed data inserted idempotently when DB is empty.

7. **Backend ↔ Frontend communication**: Next.js rewrites `/api/*` and `/v1/*` -> backend, avoiding CORS and hiding the backend URL. Auth via HttpOnly cookie (automatic in fetch with `credentials: "include"`).

# Backend Rebuild Design: free-claude-code Base + Commerce Layer

**Date**: 2026-06-05
**Status**: Draft
**Scope**: Replace the current backend with a new backend built on free-claude-code's architecture, retaining all commerce functionality.

## 1. Architecture Overview

The new backend is a single FastAPI application with two layers:

| Layer | Source | Responsibility |
|---|---|---|
| Protocol/Proxy | free-claude-code | Anthropic Messages API routing, model resolution, provider abstraction, SSE streaming |
| Commerce | cloude-gateway | User auth, API key management, billing/deduction, usage tracking, admin CRUD |

The layers integrate at **API key authentication**: free-claude-code's `require_api_key` dependency is adapted to look up keys from the database, resolving the associated User for balance and billing.

### Directory Structure

```
backend/
├── api/                  ← free-claude-code (protocol layer)
│   ├── routes.py             # /v1/messages, /v1/models, /v1/messages/count_tokens, /health
│   ├── services.py           # ClaudeProxyService
│   ├── model_router.py       # Model resolution
│   ├── dependencies.py       # API key auth (adapted: DB-backed key lookup)
│   ├── admin_routes.py       # free-claude-code runtime admin panel (pruned — not needed)
│   ├── admin_config.py       # free-claude-code runtime admin config (pruned — not needed)
│   └── ...
├── core/                 ← free-claude-code (protocol utilities)
│   ├── anthropic/            # SSE, token counting, format conversion
│   ├── trace.py              # Tracing
│   └── rate_limit.py         # Rate limiting
├── providers/            ← free-claude-code (provider abstraction)
│   ├── base.py               # BaseProvider
│   ├── registry.py           # ProviderRegistry
│   ├── deepseek/             # DeepSeek ← first provider
│   └── ...                   # Additional providers added later
├── config/               ← free-claude-code + commerce settings
│   ├── settings.py           # Extended Settings (provider + commerce fields)
│   ├── paths.py
│   └── logging_config.py
├── app/                  ← cloude-gateway (commerce layer)
│   ├── models/               # User, ApiKey, Model, Provider, ProviderKey,
│   │                         # Channel, ChannelKey, RequestLog, BillingRecord,
│   │                         # RedemptionCode, Payment
│   ├── schemas/              # Pydantic request/response schemas
│   ├── routers/              # auth, api_keys, admin_models, admin_providers,
│   │                         # admin_channels, usage, redemption, payment
│   ├── services/             # billing_service, usage_service, provider_service
│   ├── database.py           # SQLAlchemy async engine + session
│   ├── dependencies.py       # JWT auth dependency
│   ├── config.py             # Commerce-specific settings
│   ├── exceptions.py         # AppException
│   └── seed.py               # Database seed data
├── alembic/              ← Database migrations
├── tests/                ← All tests
├── server.py             ← Entry point
├── pyproject.toml        ← uv project config
└── uv.lock               ← Lockfile
```

## 2. API Routes

### Protocol Routes (from free-claude-code, Anthropic format)

```
POST   /v1/messages                  ← Chat messages proxy (SSE streaming)
HEAD   /v1/messages                  ← Compatibility probe
OPTIONS /v1/messages                 ← Compatibility probe
POST   /v1/messages/count_tokens     ← Token counting
HEAD   /v1/messages/count_tokens     ← Compatibility probe
OPTIONS /v1/messages/count_tokens    ← Compatibility probe
GET    /v1/models                    ← Model listing
GET    /health                       ← Health check
GET    /                             ← Root status
```

### Commerce Routes (from cloude-gateway, preserved)

```
POST   /api/auth/login               ← User login
POST   /api/auth/register            ← User registration
GET    /api/auth/me                  ← Current user info
POST   /api/api-keys                 ← Create API key
GET    /api/api-keys                 ← List API keys
DELETE /api/api-keys/{id}            ← Delete API key
GET    /api/usage                    ← Usage records
POST   /api/redemption               ← Redeem code
GET    /api/payment                  ← Payment records
```

### Admin Routes (from cloude-gateway, preserved)

```
/api/admin/models                    ← Model CRUD
/api/admin/providers                 ← Provider CRUD
/api/admin/channels                  ← Channel CRUD
```

## 3. Authentication & Authorization

### Protocol Layer: API Key Authentication

`/v1/*` routes use `x-api-key: sk-...` header.

1. Extract API key from header
2. Look up `ApiKey` in database (with joined User)
3. Verify key is active
4. Return (User, ApiKey) tuple for downstream billing

### Commerce Layer: JWT Authentication

`/api/*` routes use `Authorization: Bearer <jwt>` header.

Preserved from current implementation.

## 4. Data Model Changes

### Tables Preserved (unchanged)

- `users` — User accounts with balance
- `api_keys` — User-facing API keys
- `provider_keys` — Encrypted upstream API keys (key pool)
- `request_logs` — Raw request/response logging
- `billing_records` — Billing transactions
- `redemption_codes` — Balance redemption codes
- `payments` — Payment records

### Tables Modified

**`models`** — Add `cache_read_price`:
```sql
ALTER TABLE models ADD COLUMN cache_read_price INTEGER NOT NULL DEFAULT 0;
-- micro yuan per token (same unit as input_price, output_price)
```

**`providers`** — Scope `adapter` field:
- Was: `"openai-chat-completions"` or `"anthropic-messages"`
- Now: Always `"anthropic-messages"` (only Anthropic protocol going forward)

### New Tables

**`channel_keys`** — Many-to-many: Channel ↔ ProviderKey:
```sql
CREATE TABLE channel_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    provider_key_id INTEGER NOT NULL REFERENCES provider_keys(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel_id, provider_key_id)
);
```

### Pricing Formula (3-segment)

```
cost_cents = input_tokens × input_price
           + output_tokens × output_price
           + cache_read_input_tokens × cache_read_price
```

All prices in micro yuan per token. Result converted to cents (÷100).

## 5. Streaming Billing Flow

Since Anthropic Messages API is SSE streaming by default, billing must handle concurrent stream + charge:

```
Client Request (POST /v1/messages + x-api-key)
  │
  ▼
① Authenticate: Look up ApiKey → User → read balance
  │
  ▼
② Pre-flight check: balance ≥ minimum threshold (¥1.00)?
  │  No → 402 INSUFFICIENT_BALANCE
  │  Yes ↓
  ▼
③ Estimate max cost:
     estimated = (input_tokens × input_price) + (max_tokens × output_price)
     (ignore cache_read in estimate; it's bounded by input_tokens)
  │
  ▼
④ Pre-reserve: SELECT ... FOR UPDATE on user balance row
     reserve_amount = min(estimated, MAX_COST_CENTS)
     If balance < reserve_amount → reserve all remaining balance
  │
  ▼
⑤ Proxy: Provider streams SSE response to client
     Accumulate actual usage from SSE events (message_stop → usage)
  │
  ▼
⑥ Settle (after stream ends):
     actual_cost = compute_cost(
         input_tokens, output_tokens, cache_read_tokens,
         input_price, output_price, cache_read_price,
         channel_multiplier
     )
     actual_cost = min(actual_cost, MAX_COST_CENTS)
     release reserved amount
     deduct actual cost from balance
  │
  ▼
⑦ Record: write RequestLog + BillingRecord, commit transaction
```

**Edge cases**:
- Stream interrupted mid-way: charge for actual tokens consumed (from available usage data)
- Concurrent requests: `SELECT ... FOR UPDATE` prevents double-spend
- Pre-reserve exceeds balance: allow it (pre-flight threshold is the gate), settle actual

## 6. Provider Integration

### Startup: Build Provider Registry from Database

1. Query all `providers` where `status = 'active'`
2. For each, query associated `provider_keys` where `status = 'active'`
3. Map provider name → provider class (e.g., `"deepseek"` → `DeepSeekProvider`)
4. Register each provider instance in `ProviderRegistry` with its key pool

### Request: Route Model → Provider

1. `ModelRouter` resolves `request.model` → database `Model` record
2. Model → Provider association → get provider from `ProviderRegistry`
3. Provider already holds active upstream API key(s)
4. If channel is configured, select key from the channel's key subset

### Key Pool Strategy

- Default: round-robin or random selection from active keys
- Channel-scoped: select from `channel_keys` subset only
- Revoked keys are excluded at query time

### Adding a New Provider (Future)

1. Add provider class under `providers/<name>/`
2. Add mapping entry: provider name string → class
3. Add provider record in database via admin panel
4. No code changes needed in routing or billing layers

## 7. Error Handling

| Layer | Source | Format | Example |
|---|---|---|---|
| Protocol | ProviderError, upstream failures | Anthropic error: `{"type":"error","error":{"type":"...","message":"..."}}` | `{"type":"error","error":{"type":"api_error","message":"..."}}` |
| Protocol | RequestValidationError | Standard 422 + log summary | — |
| Commerce | AppException (insufficient balance, invalid key) | `{"error":"...","code":"..."}` | `{"error":"余额不足","code":"INSUFFICIENT_BALANCE"}` |

Error codes preserved from current implementation:
- `INSUFFICIENT_BALANCE` (402)
- `UNSUPPORTED_MODEL` (400)
- `NO_AVAILABLE_CHANNEL` (400)
- `PROVIDER_UNAVAILABLE` (500)
- `INVALID_API_KEY` (401)
- `VALIDATION_ERROR` (422)
- `UPSTREAM_ERROR` (502)
- `UPSTREAM_TIMEOUT` (504)
- `UPSTREAM_USAGE_MISSING` (502)
- `INTERNAL_ERROR` (500)

## 8. Technology Stack

| Component | Choice | Source |
|---|---|---|
| Python | 3.14+ (follow free-claude-code) | — |
| Package manager | uv | free-claude-code |
| Web framework | FastAPI | Both |
| ORM | SQLAlchemy 2.0 (async) | cloude-gateway |
| Migrations | Alembic | cloude-gateway |
| Database | PostgreSQL (primary), SQLite (dev) | cloude-gateway |
| Logging | loguru | free-claude-code |
| HTTP client | httpx | Both |
| Settings | pydantic-settings | Both |
| Formatter/Linter | ruff | free-claude-code |
| Type checker | ty (or mypy) | free-claude-code |
| Testing | pytest | Both |

## 9. Frontend Adaptation

The Next.js frontend is preserved. Required changes:

1. **API base URL**: Client-side calls switch from `/api/v1/chat/completions` (OpenAI format) to `/v1/messages` (Anthropic format)
2. **Auth header**: Change from `Authorization: Bearer sk-...` (current format) to `x-api-key: sk-...` (Anthropic convention). Both carry the same API key; the header name differs.
3. **Request format**: Change from OpenAI ChatCompletion format to Anthropic Messages format
4. **Response handling**: Change from JSON response to SSE stream parsing
5. **Model list**: Adapt to `/v1/models` response format

All other frontend routes (auth, API key management, usage, admin) remain unchanged.

## 10. Testing Strategy

- **Provider tests** (`tests/providers/`): free-claude-code's existing smoke tests for provider behavior
- **Commerce tests** (`tests/app/`): Current cloude-gateway tests for billing, auth, API keys
- **Integration tests**: End-to-end: API key auth → proxy → billing record
- **CI checks**: `uv run ruff format && uv run ruff check && uv run pytest`
- **Coverage target**: All new/modified code paths covered

## 11. Scope & Phasing

**Phase 1 (this spec)**:
- Copy free-claude-code core into backend/
- Adapt API key auth to DB lookup
- Implement streaming billing flow
- DeepSeek provider only
- Prune unused free-claude-code providers/messaging/CLI modules
- Add channel_keys table + channel-scoped key routing

**Phase 2 (future)**:
- Add more providers as needed
- Frontend adaptation for Anthropic Messages format

**Out of scope (this spec)**:
- Provider additions beyond DeepSeek
- Frontend changes (spec'd separately)
- free-claude-code's messaging/CLI system (not needed for API gateway use case)

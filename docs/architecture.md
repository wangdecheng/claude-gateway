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
│  /(user)/*          │      │  /admin/*  Admin routes      │
│  /admin/*           │      │                              │
└─────────────────────┘      └──────────┬───────────────────┘
                                        │
                          ┌─────────────┴──────────────┐
                          │     providers/              │
                          │  DeepSeekProvider           │
                          │  (AnthropicMessagesTransport)│
                          └─────────────┬──────────────┘
                                        │
                              ┌─────────┴─────────┐
                              │  api.deepseek.com │
                              │  /anthropic       │
                              └───────────────────┘
```

## Module Map

```
backend/
├── server.py                    # Entry point: uv run uvicorn server:app
├── api/                         # Anthropic-compatible API layer + app factory
│   ├── app.py                   # FastAPI app factory (create_app), lifespan
│   ├── routes.py                # Anthropic Messages API routes (non-billing)
│   ├── services.py              # Anthropic protocol handlers
│   ├── model_router.py          # Model→Provider resolution (DB-backed)
│   ├── dependencies.py          # API key auth dependency
│   ├── validation_log.py        # Request validation error logging
│   └── routers/                 # Commerce + admin routes
├── app/                         # Commerce layer (ported from backend-old)
│   ├── database.py              # Base, engine/session factory
│   ├── dependencies.py          # JWT auth dependency (cookie), admin check
│   ├── exceptions.py            # AppException
│   ├── seed.py                  # Idempotent seed data
│   ├── models/                  # SQLAlchemy ORM models
│   ├── routers/                 # FastAPI route modules
│   ├── schemas/                 # Pydantic request/response models
│   └── services/                # Business logic
├── config/                      # Centralized configuration
│   ├── settings.py              # Pydantic Settings (all env vars)
│   ├── logging_config.py        # Loguru structured logging
│   ├── paths.py                 # ~/.fcc/ paths
│   ├── provider_catalog.py      # Registered provider descriptors
│   ├── constants.py             # Shared defaults
│   └── nim.py                   # NVIDIA NIM params (unused)
├── providers/                   # Pluggable AI provider abstraction
│   ├── base.py                  # BaseProvider ABC + ProviderConfig
│   ├── registry.py              # ProviderRegistry (factory + cache)
│   ├── anthropic_messages.py    # SSE streaming transport
│   ├── rate_limit.py            # GlobalRateLimiter
│   ├── error_mapping.py         # Exception → ProviderError mapping
│   ├── exceptions.py            # ProviderError hierarchy
│   ├── defaults.py              # Default base URLs
│   ├── model_listing.py         # Model list parsers
│   └── deepseek/                # DeepSeek adapter
│       ├── __init__.py
│       ├── client.py            # DeepSeekProvider
│       └── request.py           # Request body builder
├── core/                        # Low-level protocol primitives
│   ├── trace.py                 # Request tracing with session ID
│   ├── rate_limiting.py         # Rate limit token bucket
│   └── anthropic/               # Anthropic protocol primitives
├── alembic/                     # Database migrations
│   ├── env.py
│   └── versions/
└── tests/                       # Backend tests
    └── test_app_startup.py

frontend/
├── middleware.ts                # JWT verification + route gating
├── next.config.ts               # Proxy /api/* → localhost:8082
├── app/
│   ├── layout.tsx               # Root layout (Providers wrapper)
│   ├── (auth)/                  # Public: login, register, forgot/reset password
│   ├── (user)/                  # Authenticated: dashboard, models, keys, usage...
│   │   └── layout.tsx           # Nav bar + balance
│   └── admin/                   # Admin: models, channels, providers CRUD
│       └── layout.tsx           # Sidebar + role check
├── components/
│   ├── Providers.tsx            # TanStack Query + Auth context
│   ├── ui/                      # shadcn/ui primitives
│   ├── forms/                   # Form components (react-hook-form + zod)
│   └── data/                    # Data display components
├── lib/
│   ├── api/client.ts            # Generic fetch wrapper
│   ├── api/*.ts                 # Domain-specific TanStack Query hooks
│   ├── auth/AuthContext.tsx      # Auth state management
│   └── utils/                   # cn(), formatPrice(), maskSK()
└── tests/                       # Frontend tests (Vitest + Testing Library)
```

## Data Flow: API Proxy Request

```
Client sends POST /v1/messages
  │
  ▼
[Next.js proxy]  ──rewrite──>  [FastAPI proxy.py]
                                    │
                    1. Auth: require_api_key → (User, ApiKey)
                    2. Resolve: ModelRouter.resolve_from_db()
                       → (Model, ChannelConfig, Provider)
                    3. Key pool: get_active_upstream_key()
                       → decrypted provider API key
                    4. Pre-flight: check balance ≥ 100 cents
                    5. Reserve: FOR UPDATE user, deduct estimated cost
                    6. Stream: provider.stream_response()
                       → DeepSeekProvider → AnthropicMessagesTransport
                       → httpx stream → SSE chunks
                    7. Settle: compute actual cost, adjust balance,
                       write RequestLog + BillingRecord
                    8. Respond: SSE stream to client
```

## Key Design Decisions

1. **Dual auth system**: JWT cookies for commerce UI, API keys for proxy. Separate dependency chains, shared User model.

2. **Pre-reserve billing**: Balance is reserved before streaming, settled after. Uses PostgreSQL row-level locks (`FOR UPDATE`) to prevent race conditions. Minimum balance 100 cents (1 yuan).

3. **Provider plugin system**: `BaseProvider` ABC with `stream_response()`, `list_model_ids()`, `cleanup()`. Factory registry keyed by provider_id. Cached instances (key = provider_id + sha256(api_key)). Only DeepSeek implemented; other providers can be added by implementing the ABC.

4. **Configuration cascade**: `.env` (project) → `~/.fcc/.env` (managed) → `$FCC_ENV_FILE` (explicit). Pydantic Settings reads all of them.

5. **Database auto-create**: Tables created in lifespan if missing. Alembic for production schema changes. Seed data inserted idempotently.

6. **Backend ↔ Frontend communication**: Next.js rewrites `/api/*` → backend, avoiding CORS and hiding backend URL. Auth via HttpOnly cookie (automatic in fetch with `credentials: "include"`).

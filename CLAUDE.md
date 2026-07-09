# CLAUDE.md

## Project Overview

**high-api** (cloude-gateway) — API relay/gateway proxying Anthropic Messages API to upstream providers (DeepSeek) with commerce: user auth, API key management, per-token billing, redemption codes, admin model/provider/channel management.

- **Backend**: Python 3.14 / FastAPI / SQLAlchemy async / PostgreSQL
- **Frontend**: Next.js 15 (App Router) / React 19 / TanStack Query / Tailwind CSS 4
- **Package manager**: `uv` (Python), `npm` (Node)

## 开发场景 → 文档映射

开发时先读 CLAUDE.md 获取概览，再按场景读对应文档。

| 场景 | 文档 | 关键入口 |
|------|------|----------|
| 代理/计费 (POST /v1/messages) | `docs/backend-proxy.md` | `backend/app/routers/proxy.py`, `app/services/billing/` (异步 pending + worker) |
| 认证/权限 (JWT, API Key) | `docs/backend-auth.md` | `backend/app/dependencies.py`, `frontend/middleware.ts` |
| 新增 AI Provider | `docs/backend-providers.md` | `backend/providers/base.py`, `registry.py` |
| 数据库模型/迁移/种子 | `docs/backend-database.md` | `backend/app/models/`, `backend/alembic/` |
| 前端页面/组件 | `docs/frontend.md` | `frontend/app/`, `lib/api/`, `components/forms/` |
| Admin CRUD | `docs/frontend.md` § Admin + `docs/backend-database.md` | `frontend/app/admin/`, `backend/app/routers/admin_*.py` |
| 测试 | `docs/testing.md` | `backend/tests/`, `frontend/tests/` |
| 整体架构 | `docs/architecture.md` | `backend/api/app.py`, `frontend/middleware.ts` |
| 速率限制 | `docs/backend-providers.md` § 速率限制 | `backend/providers/rate_limit.py` |
| 部署 / 推送 | `docs/deploy.md` | `bin/deploy.sh` |

文档: `docs/{architecture,backend-proxy,backend-auth,backend-providers,backend-database,frontend,testing,deploy}.md`

## Prerequisites

```bash
# Python: uv (>=0.9), Python 3.14 | Node: >=22 | PostgreSQL 17 (Docker)
# Fix uv cache permissions (macOS):
sudo chown -R $(whoami):staff ~/.cache/uv/
```

## Quick Start

```bash
# 1. PostgreSQL
docker run -d --name cloude-gateway-postgres \
  -e POSTGRES_USER=high_api -e POSTGRES_PASSWORD=high_api_dev \
  -e POSTGRES_DB=high_api -p 5432:5432 postgres:17

# 2. Backend (terminal 1)
cd backend && uv sync && uv run uvicorn server:app --host 0.0.0.0 --port 8082 --reload

# 3. Frontend (terminal 2)
cd frontend && npm install && npm run dev

# Backend: http://localhost:8082 | Frontend: http://localhost:3000
# Health: curl http://localhost:8082/api/health
# macOS: export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

## Commands

**Backend** (`cd backend`): `uv sync` | `uv run uvicorn server:app --host 0.0.0.0 --port 8082 --reload` | `uv run pytest` | `uv run pytest tests/file.py::test_name -v` | `uv run alembic upgrade head` | `uv run alembic revision --autogenerate -m "desc"` | `uv run ruff check .` | `uv run ruff format .` | `uv run python -m app.seed`

Tests use SQLite in-memory (`DATABASE_URL=sqlite+aiosqlite:///:memory:`), no PostgreSQL needed.

**Frontend** (`cd frontend`): `npm run dev` | `npm run build` | `npm test` (vitest run) | `npm run test:watch` | `npm run lint`

## Architecture

```
┌──────────────┐  /api/* → localhost:8082  ┌──────────────────┐
│  Next.js :3000│ ────────────────────────> │  FastAPI :8082   │
└──────────────┘ <──────────────────────── └────────┬─────────┘
                                                    │ providers/ → DeepSeekProvider → api.deepseek.com
```

### Backend Layers

```
server.py → api/app.py (factory + lifespan)
  ├─ api/routes.py              Anthropic-compatible non-billing routes
  ├─ app/routers/proxy.py       Billing POST /v1/messages
  ├─ app/routers/auth.py        JWT cookie auth
  ├─ app/routers/{api_keys,models,usage,payment,redemption,v1_models}.py
  ├─ app/routers/admin_{models,providers,channels}.py
  ├─ api/model_router.py        Model → DB provider/channel resolution
  ├─ providers/                 base.py (ABC), registry.py, anthropic_messages.py (SSE),
  │                             rate_limit.py, deepseek/client.py, exceptions.py
  ├─ config/                    Pydantic Settings, logging
  ├─ core/                      Tracing, Anthropic protocol primitives
  └─ app/services/              billing/ (compute,pending,settle,worker), auth, payments
```

### Frontend Layers

```
app/
 ├─ layout.tsx              Root layout + Providers
 ├─ middleware.ts            JWT verification, auth routing, admin gating
 ├─ (auth)/                 Login, register, forgot/reset password
 ├─ (user)/                 Dashboard, models, keys, usage, recharge, redeem, settings
 └─ admin/                  CRUD: models, channels, providers

lib/
 ├─ api/client.ts           fetch wrapper (credentials: "include")
 ├─ api/{auth,models,keys,usage,payment,redemption}.ts  + admin/*.ts
 ├─ auth/AuthContext.tsx    Auth state (user, isLoading, refetch, logout)
 └─ utils/                  cn(), formatPrice(), maskSK()

components/
 ├─ Providers.tsx           QueryClientProvider + AuthProvider
 ├─ ui/                     shadcn/ui primitives
 ├─ forms/                  react-hook-form + zod forms
 └─ data/                   BalanceDisplay, KeyList, ModelCard
```

### Key Flows

**Auth**: Two parallel systems — JWT (HttpOnly cookie `high_api_session`) for UI; API Key (Bearer `sk-...`) for proxy. Frontend middleware verifies JWT with `jose`; backend `get_current_user` reads cookie → fetches user.

**Billing (POST /v1/messages)** - **async pending + worker, NOT pre-reserve**: ① Validate API key -> `(user, api_key)` ② Resolve model via `ModelRouter` -> `Model` -> `ModelProviderRoute` (table `model_providers`) -> `Provider` ③ Token coefficient (discount) via `TokenCoefficientService.get_for_model()` ④ Pick upstream key from `provider_keys` pool (AES-256-GCM, `channel_keys` subset if bound) ⑤ Pre-flight: `balance >= 10` (¥0.10), **no reservation** ⑥ Stream SSE response, rewriting each chunk in-flight (provider model name -> original Claude name, apply coefficient) and accumulating usage ⑦ `finally`: write `pending_billings` row (`request_id` UNIQUE) ⑧ `BillingWorker` (asyncio task, every 30s, `FOR UPDATE SKIP LOCKED`) settles each row: `compute_cost` -> `FOR UPDATE` user -> `balance -= cost` -> write `RequestLog` + `BillingRecord` + `UsageRecord`; retries 3x then `dead`. Prices in micro-yuan/1K tokens; billing in fen. **Note**: `app/services/billing_service.py` is LEGACY (synchronous, retired `ChannelConfig`); active path is `app/services/billing/{compute,pending,settle,worker,token_coefficient}.py`.

**Database**: SQLAlchemy async (asyncpg/aiosqlite). Tables auto-created on startup; Alembic for production migrations. Seed data inserted idempotently. `FOR UPDATE` locking on balance; UNIQUE on `billing_records.request_log_id` (anti-double-charge) and `payment_records.transaction_id` (idempotency).

**Config**: `.env` (project) → `~/.fcc/.env` (production) → `FCC_ENV_FILE` override.

## Important Notes

- `backend-old/` is predecessor — reference only, NOT active codebase.
- Provider encryption: AES-256-GCM, provider_id as AAD, keys stored base64 in `provider_keys.key_encrypted`.
- Redemption codes: bcrypt hashed, prefix match (`REDM-XXXX-XXXX-XXXX`).
- Frontend rewrites `/api/*` → `localhost:8082/api/*` (hardcoded in `next.config.ts`).
- App factory creates missing tables on startup — fresh DBs work without migrations.

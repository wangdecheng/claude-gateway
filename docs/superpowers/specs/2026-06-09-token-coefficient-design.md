# Token Coefficient (Discount) — Design Spec

**Date**: 2026-06-09
**Status**: approved

## Summary

Let admin multiply the `input_tokens` / `cache_creation_input_tokens` / `output_tokens` values returned to API clients (and used for billing) by a single coefficient in `(0, 1]`. Apply globally by default, with optional per-model overrides. Used to grant token discounts without touching upstream integration or per-model pricing.

**Note (2026-06-21):** `cache_read_input_tokens` is **not** discounted — it is passed through at the raw upstream value. See [`2026-06-21-token-coefficient-cache-read-passthrough-design.md`](2026-06-21-token-coefficient-cache-read-passthrough-design.md) for the rationale and behaviour change.

## Goals

- Admin can configure a global coefficient and per-model overrides from the admin UI.
- The same adjusted values are written into the API response (Anthropic Messages SSE) and the `UsageRecord` / `BillingRecord` (i.e. what the user sees = what they pay for).
- The coefficient takes effect immediately after the admin saves it; no service restart needed.
- Rounding: `ceil(actual * coefficient)` so a 0.5× coefficient never rounds below half a token.
- Coefficient `= 1.0` is a fast path — zero behavioural change, byte-identical SSE output.

## Non-Goals

- Per-token-type coefficients — single coefficient covers all three discounted fields. (Per the 2026-06-21 delta spec, `cache_read_input_tokens` is excluded from the discount; this is a scope narrowing, not a per-field coefficient knob.)
- Per-user / per-user-group coefficients — out of scope.
- Charging the user the full amount while only showing a discount in the response — out of scope; we apply it consistently to both.
- Returning the original (un-adjusted) values anywhere in the response — the client only ever sees the adjusted values.
- Persisting the raw upstream values alongside the adjusted ones for audit — can be added later; not in this iteration.

## Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Storage | New dedicated table `token_coefficient_configs` | Audit/revert is trivial; doesn't bloat `models` or `providers` |
| Scope granularity | Global default + per-model override | Matches user choice; balances simplicity and flexibility |
| Per-token-type coefficient | Single value for all four fields | Matches user choice; sufficient for the common "give 20% off" case |
| Rounding | `math.ceil` | Matches user choice; ceil with `<1` coefficient never under-discounts |
| Where to rewrite SSE | Wrap the provider's async stream in `proxy.py` | Provider layer stays unaware; single chokepoint for response and billing |
| Where to adjust for billing | Same coefficient applied in the settlement path (`billing_stream` finally block) | Guarantees response and billing use identical numbers |
| Cache | In-memory dict loaded at startup, invalidated on admin write | One DB read at boot; O(1) lookup per request; admin change is rare |
| Coefficient > 1 (markup) | Reject at the Pydantic layer (must be `0 < x <= 1`) | Out of scope; prevents accidental over-charging |
| Coefficient = 0 (free) | Reject (`x > 0`) | Prevents footgun; users can disable by setting 1.0 |

## Changes

### 1. Database — new table

```sql
CREATE TABLE token_coefficient_configs (
    id SERIAL PRIMARY KEY,
    scope_type VARCHAR(10) NOT NULL,                  -- 'global' | 'model'
    model_id INTEGER REFERENCES models(id) ON DELETE CASCADE,
    coefficient DOUBLE PRECISION NOT NULL CHECK (coefficient > 0 AND coefficient <= 1),
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMETZ NOT NULL DEFAULT NOW(),
    created_at TIMETZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_model_scope UNIQUE (model_id),       -- at most 1 override per model
    CONSTRAINT chk_scope_model_match CHECK (
        (scope_type = 'global' AND model_id IS NULL) OR
        (scope_type = 'model'  AND model_id IS NOT NULL)
    )
);
-- Global uniqueness is enforced at the application layer: at most one row with scope_type='global'.
```

Alembic migration `014_*`:
- Creates the table
- Inserts the seed global row: `INSERT INTO token_coefficient_configs (scope_type, coefficient) VALUES ('global', 1.0)`

### 2. Backend — new files

```
backend/app/models/token_coefficient.py            # ORM model
backend/app/schemas/token_coefficient.py           # Pydantic schemas
backend/app/routers/admin_token_coefficients.py   # Admin CRUD router
backend/app/services/token_coefficient_service.py  # Resolution + in-memory cache
backend/app/services/billing/token_coefficient.py  # Pure function apply_coefficient()
backend/app/services/streaming/sse_rewrite.py      # Pure function _apply_coefficient_to_sse_event()
backend/alembic/versions/014_*.py                  # Migration
```

### 3. Backend — modified files

**Actual flow** (as of this writing):
```
create_message (proxy.py:146)
  → async for chunk in provider_instance.stream_response(...)
      · accumulated_usage  ← raw tokens extracted from SSE
      · yield chunk        ← raw chunk sent to client
  → finally: write_pending_billing(db, ... input_tokens=accumulated_usage[...])
  → StreamingResponse(billing_stream(), ...)

[Background, separate process step]
BillingWorker → settle_one(db, pending)
  → compute_costs_for_pending(pending, db)  ← reads pending.*_tokens, calls compute_cost
  → write RequestLog, BillingRecord, UsageRecord  ← all copy from pending.*_tokens
```

Two places need to apply the coefficient so response and billing stay aligned:

- **`backend/app/routers/proxy.py`** — `create_message` / `billing_stream` (inner async function):
  1. Look up the coefficient once at request entry via `request.app.state.token_coefficient_service.get_for_model(model.id)`.
  2. After the upstream yields a chunk, rewrite the chunk's `usage` JSON via `_apply_coefficient_to_sse_event(chunk, coefficient)` **before** yielding to the client — so the client sees the discounted values.
  3. In the `finally` block, apply `apply_coefficient()` to `accumulated_usage` **before** passing to `write_pending_billing` — so settlement (which reads from `PendingBilling` row) charges the discounted amount.
- **`backend/api/app.py`** — lifespan: instantiate `TokenCoefficientService`; on startup call `.load()`; on admin write call `.invalidate()` (from the router); store on `app.state`.
- **`backend/app/routers/admin_token_coefficients.py`** — call `app.state.token_coefficient_service.invalidate()` after every successful PUT/DELETE.
- `frontend/app/admin/layout.tsx` (or equivalent nav config) — add a "折扣配置" link.

### 4. Coefficient resolution priority

For a request routed to `model_id = M` (the gateway `Model.id`, resolved by `_lookup_model` in `proxy.py`):

1. If `M` has an override row → return `override.coefficient`.
2. Else if `scope_type='global'` row exists → return `global.coefficient`.
3. Else → return `1.0` (defensive default; in practice the seed row always exists).

### 5. Pydantic schemas

```python
class TokenCoefficientBase(BaseModel):
    coefficient: float = Field(..., gt=0, le=1)

class TokenCoefficientGlobalUpdate(TokenCoefficientBase): ...

class TokenCoefficientModelUpsert(TokenCoefficientBase): ...

class TokenCoefficientModelOut(BaseModel):
    model_id: int
    model_name: str
    model_public_name: str
    coefficient: float
    updated_at: datetime
    updated_by_username: str | None

class TokenCoefficientsOverview(BaseModel):
    global_coefficient: float
    overrides: list[TokenCoefficientModelOut]
```

### 6. Admin API

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/api/admin/token-coefficients` | — | `TokenCoefficientsOverview` |
| PUT | `/api/admin/token-coefficients/global` | `{ coefficient }` | `{ coefficient, updated_at }` |
| PUT | `/api/admin/token-coefficients/models/{modelId}` | `{ coefficient }` | `TokenCoefficientModelOut` |
| DELETE | `/api/admin/token-coefficients/models/{modelId}` | — | 204 |

All endpoints require admin auth (existing dependency, same as other `/admin/*` routes). All return 400/422 on validation failure.

### 7. Pure functions

```python
# backend/app/services/billing/token_coefficient.py
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class AdjustedUsage:
    input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int

def apply_coefficient(
    *,
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    output_tokens: int,
    coefficient: float,
) -> AdjustedUsage:
    if coefficient == 1.0:
        return AdjustedUsage(
            input_tokens, cache_read_tokens,
            cache_creation_tokens, output_tokens,
        )
    return AdjustedUsage(
        input_tokens=math.ceil(input_tokens * coefficient),
        cache_read_tokens=cache_read_tokens,  # pass-through: cache read not discounted
        cache_creation_tokens=math.ceil(cache_creation_tokens * coefficient),
        output_tokens=math.ceil(output_tokens * coefficient),
    )
```

```python
# backend/app/services/streaming/sse_rewrite.py
import json, math
from typing import Iterable, Tuple

USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)

def _apply_coefficient_to_usage_dict(usage: dict, coefficient: float) -> dict:
    if coefficient == 1.0:
        return usage
    out = dict(usage)
    for f in USAGE_FIELDS:
        v = out.get(f)
        if isinstance(v, int) and v >= 0:
            out[f] = math.ceil(v * coefficient)
    return out

def _apply_coefficient_to_sse_event(event: str, coefficient: float) -> str:
    """Rewrite a single SSE event (possibly multi-line) so that any data: line whose
    payload contains a 'usage' dict has its token counts multiplied by coefficient.
    Non-data lines, lines whose JSON lacks 'usage', and unparseable data are
    passed through unchanged."""
    if coefficient == 1.0:
        return event
    lines = event.split("\n")
    out_lines: list[str] = []
    for line in lines:
        if not line.startswith("data:"):
            out_lines.append(line)
            continue
        payload = line[len("data:"):].lstrip()
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            out_lines.append(line)
            continue
        if not isinstance(obj, dict) or "usage" not in obj or not isinstance(obj["usage"], dict):
            out_lines.append(line)
            continue
        obj["usage"] = _apply_coefficient_to_usage_dict(obj["usage"], coefficient)
        out_lines.append("data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(out_lines)
```

### 8. SSE rewrite in `proxy.py` (inside `billing_stream`)

The actual code path lives inside the inner `billing_stream` async function in `create_message`. We modify it in two places:

**In the streaming loop** (where the chunk is yielded to the client):
```python
async for chunk in provider_instance.stream_response(provider_body, request_id=...):
    # Existing usage extraction (unchanged)
    usage = _extract_usage_from_sse_line(chunk)
    if usage:
        for key in ("input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_creation_tokens"):
            val = usage.get(key, 0)
            if val:
                accumulated_usage[key] = val

    # Existing model remap
    if _remap_model:
        chunk = chunk.replace(_provider_model, _original_model)

    # NEW: rewrite usage in the chunk before yielding to the client.
    # cache_read_input_tokens is left at its raw upstream value (no discount).
    yield _apply_coefficient_to_sse_event(chunk, coefficient)
```

**In the `finally` block** (before `write_pending_billing`):
```python
finally:
    adjusted = apply_coefficient(
        input_tokens=accumulated_usage["input_tokens"] or 0,
        output_tokens=accumulated_usage["output_tokens"] or 0,
        cache_read_tokens=accumulated_usage["cache_read_tokens"] or 0,
        cache_creation_tokens=accumulated_usage["cache_creation_tokens"] or 0,
        coefficient=coefficient,
    )
    await write_pending_billing(
        db, request_id=uuid.uuid4(), user_id=user_id, api_key_id=api_key_id,
        model_id=model.id, route_id=routed.db_route_id, provider_id=provider.id,
        input_tokens=adjusted.input_tokens,
        output_tokens=adjusted.output_tokens,
        cache_read_tokens=adjusted.cache_read_tokens,
        cache_creation_tokens=adjusted.cache_creation_tokens,
        upstream_message_id=upstream_message_id,
    )
```

The coefficient is looked up once at the top of `create_message` and captured in the closure of `billing_stream`:
```python
coefficient = request.app.state.token_coefficient_service.get_for_model(model.id)
```

**Why not wrap the whole stream in a separate function?** The current code already does chunk-level parsing (`_extract_usage_from_sse_line`, `_extract_message_id_from_sse_line`, model remap). Inlining the rewrite avoids double-buffering the chunk and keeps the existing single-pass parser in place. `_apply_coefficient_to_sse_event` itself is a pure function that's easy to unit-test.

### 4a. Why this is a one-write fix (not two)

`PendingBilling` is the only source of truth for downstream tables. The flow is:

```
billing_stream finally: write_pending_billing(adjusted_tokens)  ← adjusted at write time
  → PendingBilling row stores ADJUSTED tokens
  → BillingWorker → settle_one → reads pending.input_tokens etc.
    → compute_costs_for_pending(pending)        ← uses ADJUSTED values
    → RequestLog(input_tokens=pending.input_tokens, ...)  ← copies ADJUSTED
    → BillingRecord(amount=computed_cost)        ← based on ADJUSTED cost
    → UsageRecord(input_tokens=pending.input_tokens, ...)  ← copies ADJUSTED
```

So we only need to call `apply_coefficient()` **once** — at the boundary where `accumulated_usage` becomes `PendingBilling.*_tokens`. The settlement layer and all derived tables inherit the discount for free. This also keeps the discount visible in user-facing usage history (`UsageRecord`) — so what the user sees in their dashboard matches what they were charged.

### 9. Frontend — new page

`frontend/app/admin/discounts/page.tsx`:
- Section A: global coefficient — `Number` input (step 0.01, min 0.01, max 1), "保存" button.
- Section B: model overrides — table using `useAdminModels` (paginated) showing:
  - `模型名` | `公开名` | `覆盖值` | `操作`
  - "设置覆盖" / "删除覆盖" buttons. "删除覆盖" disabled when no override.
  - "设置覆盖" opens a dialog with `Number` input (0 < x ≤ 1, step 0.01).
- API client: `frontend/lib/api/admin/token-coefficients.ts` with hooks `useTokenCoefficients`, `useUpdateGlobalCoefficient`, `useUpsertModelCoefficient`, `useDeleteModelCoefficient`.

The existing `/admin` middleware already protects the route. Add a sidebar link in the admin nav.

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Coefficient = 1.0 | Short-circuit; SSE rewrite is byte-identical to upstream |
| SSE `data:` JSON unparseable | Pass the line through unchanged; log `warning`; never break the stream |
| `usage` absent or non-dict | Pass through unchanged |
| `input_tokens` missing from `usage` | `get(..., None)` returns None → field skipped |
| Coefficient ≤ 0 or > 1 | Pydantic 422 (admin) |
| Coefficient invalid float (NaN, Inf) | Pydantic 422 |
| Global row missing at request time | Service falls back to `1.0` and logs a one-time warning |
| Admin write → cache stale | `invalidate()` called inside the same handler after commit |
| Provider error mid-stream | Existing error path; coefficient is irrelevant |
| `apply_coefficient` called with non-int token | TypeError; tests catch this |

## Testing

### Backend unit tests

- `test_apply_coefficient.py`:
  - `coefficient=1.0` returns the same ints (object identity may differ; values equal).
  - Ceil boundary: `7 * 0.5 → 4`, `8 * 0.5 → 4`, `1 * 0.33 → 1`.
  - All four fields independent.
  - Negative inputs (shouldn't happen) → unchanged behaviour with no crash.
- `test_sse_rewrite.py`:
  - `message_start` event with full usage → all four fields adjusted.
  - `message_delta` with only `output_tokens` → only that field adjusted.
  - `ping` event with no usage → unchanged.
  - Unparseable data line → unchanged.
  - Multi-line event with multiple `data:` lines → both rewritten.
- `test_token_coefficient_service.py`:
  - Model override wins over global.
  - Missing override → global.
  - Missing global row → returns `1.0` and logs.
  - `invalidate()` after admin write → next call uses fresh data.
- `test_admin_token_coefficients_router.py`:
  - GET returns overview with `global` and per-model overrides.
  - PUT global validates `0 < x ≤ 1`.
  - PUT model creates override (or updates existing).
  - DELETE removes override; subsequent GET reflects global.
  - 404 for non-existent model.

### Backend integration tests

- New: `test_billing_with_coefficient.py`:
  - Mock upstream SSE; with `coefficient=0.5`, the persisted `PendingBilling` row has `ceil(raw / 2)` for each field.
  - After `BillingWorker._scan_and_settle` runs, the resulting `RequestLog`, `BillingRecord`, and `UsageRecord` rows all reflect the adjusted values; `BillingRecord.amount_cents` matches `compute_cost(adjusted, prices, multiplier)`.
  - End-to-end through `POST /v1/messages` (happy path).
- Existing `test_settle.py` extended with a parameterised case `coefficient ∈ {1.0, 0.5, 0.33}` (the discount is applied at the `PendingBilling` write site, so `settle_one` itself is unchanged but tests can mutate the pending row to confirm downstream tables inherit the values).
- `test_proxy_response_with_coefficient.py` (new): mock upstream; assert that the chunks yielded to the client have the adjusted usage in `message_start` and `message_delta` events.

### Frontend tests

- `DiscountsPage.test.tsx`:
  - Renders global value and per-model rows.
  - Updating global fires `useUpdateGlobalCoefficient`; success invalidates queries.
  - Adding/editing/removing an override updates the table.
  - Validation error from server surfaces inline.
- `token-coefficients.test.ts` (API hooks) — vitest with mocked `apiClient` to verify the right URL/method/body for each hook.

### Manual smoke

- Set global to `0.5` via admin UI; `curl` `/v1/messages` with a known-input prompt; confirm `input_tokens` in response is ~half the upstream count (ceil).
- Same request → Usage record in DB has the adjusted value; balance deduction equals adjusted-token cost.
- Set model-level override; switch to that model; confirm override is used.
- Delete model override; confirm fall-back to global.

## Out-of-Scope (Future)

- Coefficient > 1 (markup for premium SKs) — easy to add by relaxing the validator.
- Per-token-type coefficient — would extend the row to 3 floats or add separate fields. (See 2026-06-21 delta spec for the cache_read exclusion, which is a scope narrowing rather than a per-field coefficient system.)
- Per-user / per-user-group coefficient — needs a join through `users` or `user_groups`.
- Caching with TTL instead of invalidate-on-write.
- Audit log of coefficient changes (table already records `updated_by` and `updated_at`; a dedicated `audit_log` row could capture old → new).
- Reporting / dashboard showing aggregate savings due to coefficients.

## Implementation Notes

Implementation plan: [`docs/superpowers/plans/2026-06-09-token-coefficient-implementation.md`](../plans/2026-06-09-token-coefficient-implementation.md).

### Commit range

```
a4352da test(frontend): add discounts page tests
0f7dbd4 feat(frontend): add admin discounts page with global + per-model config
983435b feat(frontend): add token coefficient API hooks
b4294c4 feat(proxy): apply token coefficient to SSE response and PendingBilling
c04d985 feat(app): register admin token-coefficients router and start service
e5600cb feat(router): add admin token coefficient endpoints
c0257f3 feat(service): add TokenCoefficientService with resolution and cache
9d636a1 feat(schema): add token coefficient Pydantic schemas
e673c3a feat(streaming): add pure SSE rewrite helper with tests
5f80c31 feat(billing): add pure apply_coefficient helper with tests
723a168 feat(model): add TokenCoefficientConfig ORM
af4601e feat(db): add token_coefficient_configs migration
256b454 docs(plan): add token coefficient implementation plan
14ae31e docs(spec): refine token coefficient spec to match actual proxy/settlement flow
fe48831 docs(spec): add token coefficient design spec
```

### Deviations from the literal spec

- **Public-name field name**: the spec refers to `model.name` / `model_public_name` interchangeably. The implementation exposes `model_public_name` only (the gateway's `Model.public_name`) on `TokenCoefficientModelOut`; the internal `name` slug is not surfaced. This matches the spec's intent — the admin UI shows the public-facing label.
- **Defensive `getattr` on the ORM**: the `updated_by` foreign key is loaded lazily and may be `None` if the user row was deleted (cascade on user delete is not configured). The router does `getattr(user, "username", None)` to fall back to `None` rather than raising. This is a small robustness add, not a spec change.
- **Service `invalidate()` runs on every admin write** as the spec calls out, but is also called defensively from the lifespan `shutdown` hook to be safe across test-suite teardown — not strictly required, but keeps the in-memory cache empty between test cases.
- **Alembic migration filename**: the spec placeholder was `014_*`; the actual file is `014_<rev_id>_token_coefficient_configs.py`, as is the project convention.
- **Frontend nav entry**: the spec says "add a 折扣配置 link in `frontend/app/admin/layout.tsx` (or equivalent nav config)". The implementation adds it to the existing sidebar config used by the admin layout, not a fresh file. No new file was needed.
- **Missing `app/admin/channels/page.tsx` `tsc` errors** are pre-existing and unrelated to this feature (they predate the token coefficient work and refer to a stale `ProviderOption` shape).
- **Ruff**: the new test files (`tests/test_admin_token_coefficients_router.py`, `tests/services/test_token_coefficient_service.py`) follow the project's existing pattern of `sys.path.insert` before `from app import …`, which ruff flags as `E402`. The same pattern is used in every other integration test in the suite, so this is consistent with the codebase rather than a new regression.

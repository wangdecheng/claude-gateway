# Token Coefficient (Discount) — Design Spec

**Date**: 2026-06-09
**Status**: draft

## Summary

Let admin multiply the `input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` / `output_tokens` values returned to API clients (and used for billing) by a single coefficient in `(0, 1]`. Apply globally by default, with optional per-model overrides. Used to grant token discounts without touching upstream integration or per-model pricing.

## Goals

- Admin can configure a global coefficient and per-model overrides from the admin UI.
- The same adjusted values are written into the API response (Anthropic Messages SSE) and the `UsageRecord` / `BillingRecord` (i.e. what the user sees = what they pay for).
- The coefficient takes effect immediately after the admin saves it; no service restart needed.
- Rounding: `ceil(actual * coefficient)` so a 0.5× coefficient never rounds below half a token.
- Coefficient `= 1.0` is a fast path — zero behavioural change, byte-identical SSE output.

## Non-Goals

- Per-token-type coefficients (input vs cache_read vs output) — single coefficient covers all four fields.
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

- `backend/api/app.py` — register `admin_token_coefficients` router; instantiate `TokenCoefficientService` and call `.load()` in lifespan; store on `app.state`.
- `backend/app/routers/proxy.py` — `billing_stream`:
  - Look up the coefficient once at request entry via `state.token_coefficient_service.get_for_model(model_id)`.
  - Wrap the provider stream with `_adjusted_usage_stream(raw_stream, coefficient)`.
  - Pass the same `coefficient` into the settlement path so `process_token_recording` applies it before calling `compute_cost` and writing `UsageRecord`.
- `backend/app/services/billing_service.py` — `process_token_recording` (or equivalent settlement entry point): apply `apply_coefficient()` to the raw token counts before computing cost and before persisting `UsageRecord`.
- `backend/app/routers/admin_token_coefficients.py` — call `state.token_coefficient_service.invalidate()` after every successful PUT/DELETE.
- `frontend/app/admin/layout.tsx` (or equivalent nav config) — add a "折扣配置" link.

### 4. Coefficient resolution priority

For a request routed to `model_id = M`:

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
        cache_read_tokens=math.ceil(cache_read_tokens * coefficient),
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
    "cache_read_input_tokens",
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

### 8. Stream wrapping (in `proxy.py`)

```python
async def _adjusted_usage_stream(raw_stream, coefficient: float):
    if coefficient == 1.0:
        async for chunk in raw_stream:
            yield chunk
        return
    buffer = ""
    SSE_DELIM = "\n\n"
    async for chunk in raw_stream:
        buffer += chunk
        while SSE_DELIM in buffer:
            event, buffer = buffer.split(SSE_DELIM, 1)
            yield _apply_coefficient_to_sse_event(event, coefficient) + SSE_DELIM
    if buffer:
        yield _apply_coefficient_to_sse_event(buffer, coefficient)
```

In `billing_stream`:
```python
coefficient = request.app.state.token_coefficient_service.get_for_model(model_id)
raw_stream = provider.stream_response(...)
adjusted_stream = _adjusted_usage_stream(raw_stream, coefficient)
return anthropic_sse_streaming_response(adjusted_stream)
```

In the `finally` block, hand `coefficient` to the settlement helper so it can call `apply_coefficient()` on the collected raw tokens before persisting.

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
  - Mock upstream SSE; with `coefficient=0.5`, the persisted `UsageRecord` has `ceil(raw / 2)` for each field.
  - `BillingRecord.amount` matches `compute_cost(adjusted, ...)`.
  - End-to-end through `POST /v1/messages` (happy path).
- Existing `test_settle.py` extended with a parameterised case `coefficient ∈ {1.0, 0.5, 0.33}`.

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
- Per-token-type coefficient — would extend the row to 4 floats or add separate fields.
- Per-user / per-user-group coefficient — needs a join through `users` or `user_groups`.
- Caching with TTL instead of invalidate-on-write.
- Audit log of coefficient changes (table already records `updated_by` and `updated_at`; a dedicated `audit_log` row could capture old → new).
- Reporting / dashboard showing aggregate savings due to coefficients.

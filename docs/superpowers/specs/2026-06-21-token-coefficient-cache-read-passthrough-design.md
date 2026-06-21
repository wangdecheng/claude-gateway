# Token Coefficient — Exclude cache_read from Discount

**Date**: 2026-06-21
**Status**: approved
**Supersedes**: part of [`2026-06-09-token-coefficient-design.md`](2026-06-09-token-coefficient-design.md) (this is a delta, not a replacement)

## Summary

The admin token coefficient (discount) currently multiplies **four** Anthropic token fields — `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens`. This spec narrows the discount to **three** fields: `input_tokens`, `cache_creation_input_tokens` (cache write), and `output_tokens`. `cache_read_input_tokens` is now passed through unchanged at full upstream value.

The product rationale: cache reads are already heavily discounted by upstream providers (Anthropic: ~10% of input price; DeepSeek: similarly reduced). Discounting them on top of upstream's own discount would compound the saving on a field that is already cheap, while `input_tokens` and `cache_creation_input_tokens` (the expensive cache write that occupies KV-cache space) carry the full upstream cost and benefit more from the gateway-level discount.

Single-coefficient model is preserved — the same admin coefficient still applies to the three in-scope fields, with the same global / per-model override priority and the same in-memory cache invalidation flow. No DB schema change, no API change, no UI change.

## Goals

- `cache_read_input_tokens` (and the downstream `cache_read_tokens` value seen in `PendingBilling` / `RequestLog` / `BillingRecord` / `UsageRecord`) is the **raw upstream value** regardless of coefficient.
- `input_tokens`, `cache_creation_input_tokens`, `output_tokens` continue to be multiplied by `ceil(raw * coefficient)` exactly as before.
- SSE response and billing write stay aligned (the same single set of "what the user sees" values flows into PendingBilling).
- Coefficient = 1.0 short-circuit still returns SSE byte-identical to upstream; pure function fast-path preserved.
- No migration. No historical recomputation. Effect is from the next request onward.

## Non-Goals

- **No per-token-type coefficients**. We do not add a "discount cache read at rate X" knob; cache read is hard-coded to pass-through. If a future need arises for per-field rates, that will be a separate spec that re-evaluates the data model.
- **No DB schema change**. The single `coefficient float` column stays.
- **No API or UI change**. The admin form keeps one coefficient input.
- **No historical data backfill**. Bills / usage records written before this change are not touched. Past discounts on cache reads stand.
- **No new "what's affected" column** in the admin UI. The UI just keeps the existing "系数" label; a one-line help text addition is the only UI delta (see §Changes §4).

## Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Which fields are discounted | `input_tokens`, `cache_creation_input_tokens`, `output_tokens` | Per product owner: input and cache write are the expensive fields; output is left in for the existing flow. Cache read is excluded. |
| Coefficient value range | Unchanged: `0 < x ≤ 1` | No relaxation needed — we are narrowing scope, not extending. |
| Data model | Unchanged: single `coefficient float` per row | Per-field rates out of scope. |
| Rounding | Unchanged: `math.ceil` | Same rationale as original spec — never under-discount. |
| Where to apply | Unchanged: two pure functions (`apply_coefficient` + SSE rewrite) and the single `billing_stream` finally block | Keeps response == billing invariant. |
| Admin UI hint | Add a one-line help text under the "系数" input: "适用于 input_tokens、cache_creation_input_tokens、output_tokens。cache_read_input_tokens 不参与折扣。" | Low-cost clarity for operators. |
| Historical backfill | None | Per owner: only future requests are affected. |

## Changes

### 1. `backend/app/services/billing/token_coefficient.py`

`apply_coefficient()` keeps the same signature and the `coefficient == 1.0` short-circuit. The non-1.0 branch no longer multiplies `cache_read_tokens`:

```python
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
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            output_tokens=output_tokens,
        )
    return AdjustedUsage(
        input_tokens=math.ceil(input_tokens * coefficient),
        cache_read_tokens=cache_read_tokens,  # pass-through: cache read not discounted
        cache_creation_tokens=math.ceil(cache_creation_tokens * coefficient),
        output_tokens=math.ceil(output_tokens * coefficient),
    )
```

`AdjustedUsage` dataclass is unchanged. Module docstring is updated to state which fields are affected.

### 2. `backend/app/services/streaming/sse_rewrite.py`

`USAGE_FIELDS` drops `cache_read_input_tokens`:

```python
USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)
```

`_apply_coefficient_to_usage_dict`, `_rewrite_usage_in_place`, `_apply_coefficient_to_sse_event` all keep their existing signatures and structure — they iterate `USAGE_FIELDS`, so the change is mechanical. Module docstring is updated.

The `coefficient == 1.0` short-circuit at the top of `_apply_coefficient_to_sse_event` is preserved (byte-identical SSE).

### 3. `backend/app/routers/proxy.py`

**No code change.** The call sites in `billing_stream` (the `apply_coefficient(...)` invocation in the `finally` block and `_apply_coefficient_to_sse_event(chunk, coefficient)` in the streaming loop) keep their existing argument lists. The function signatures and the `coefficient` lookup at request entry are unchanged. The behavior shift comes entirely from the two pure functions above.

### 4. Frontend — `frontend/app/admin/discounts/page.tsx`

Add a one-line help text under each coefficient input (global and per-model dialog). The current text reads:

- Global: `所有模型的默认折扣系数（0 < x ≤ 1）。1.0 表示无折扣。`
- Per-model dialog: none (only the `Label` "系数 (0 < x ≤ 1)").

New text:

- Global help: `所有模型的默认折扣系数（0 < x ≤ 1）。1.0 表示无折扣。作用于 input_tokens、cache_creation_input_tokens、output_tokens;cache_read_input_tokens 不参与折扣。`
- Per-model dialog help: add the same suffix inside the dialog, below the input.

No layout, validation, or hook change.

### 5. Tests

#### `backend/tests/services/billing/test_apply_coefficient.py`

Add:

- `test_cache_read_passthrough`: `coefficient=0.5, cache_read_tokens=8000` → result `cache_read_tokens == 8000` while the other three fields are `ceil(raw * 0.5)`.
- `test_cache_read_passthrough_at_various_coefficients`: parameterised over `coefficient ∈ {0.1, 0.33, 0.5, 0.99}` confirming `cache_read_tokens` is always equal to the input.

Adjust existing tests that may have implicitly assumed all four fields are discounted (search for `cache_read` in this file; update any `expected.coefficient` calculation that multiplied `cache_read_tokens` by `coefficient`).

#### `backend/tests/services/streaming/test_sse_rewrite.py`

Add:

- `test_cache_read_passthrough_in_sse_event`: build a `message_start` event with `usage` containing all four fields, apply `coefficient=0.5`, parse the result, assert `cache_read_input_tokens` is unchanged and the other three are `ceil(raw * 0.5)`.
- `test_cache_read_passthrough_in_message_delta`: same idea for a `message_delta` event.

Adjust any existing test that expected all four `USAGE_FIELDS` to be adjusted.

#### `backend/tests/integration/test_billing_flow.py` (if any assertion checks discounted cache read)

- Search for cache_read in existing billing flow tests. If a test seeds `PendingBilling.cache_read_tokens` with a discounted value, update it to use the raw value (or use `coefficient=1.0` to preserve the existing assertion).

#### Frontend `DiscountsPage.test.tsx`

- Add an assertion that the help text mentions "cache_creation_input_tokens" and "cache_read_input_tokens 不参与折扣" (or a stable substring of the new help text).

### 6. Spec / docs

- The original [`2026-06-09-token-coefficient-design.md`](2026-06-09-token-coefficient-design.md) §Summary currently says "multiply the `input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` / `output_tokens` values". Update that line to remove `cache_read_input_tokens` and add a "see also" pointer to this delta spec.
- §Non-Goals "Per-token-type coefficients" stays (still out of scope), but add a parenthetical: "(per the original spec; the cache_read exclusion in the 2026-06-21 delta spec is a scope narrowing, not a per-field coefficient knob)".
- §Changes §7's `USAGE_FIELDS` tuple and the `apply_coefficient` example block both need to drop `cache_read_input_tokens` and the `cache_read_tokens` `math.ceil` line.
- §Changes §8's "streaming loop" example and the "finally block" example in the original spec also need updating for the new behaviour.
- §Out-of-Scope "Per-token-type coefficient" line stays but with a pointer: "(see 2026-06-21 delta spec for the cache_read exclusion, which is a scope narrowing rather than a per-field coefficient system)".

## Data Flow (after change)

```
upstream SSE event
  → provider normaliser (cache_creation fill, etc.)
  → proxy._apply_coefficient_to_sse_event(chunk, coefficient)
      rewrites usage in-place:
        input_tokens:                ceil(raw * coef)
        cache_creation_input_tokens: ceil(raw * coef)
        output_tokens:               ceil(raw * coef)
        cache_read_input_tokens:     raw   ← pass-through
  → yield to client  (client sees adjusted usage)
  → billing_stream finally:
      adjusted = apply_coefficient(..., coefficient=coefficient)
      write_pending_billing(input_tokens, cache_creation_tokens, output_tokens, cache_read_tokens)
        → PendingBilling stores adjusted values
        → BillingWorker → settle_one → RequestLog / BillingRecord / UsageRecord
            all inherit adjusted values
```

The response/billing invariant is preserved: `cache_read_tokens` the client sees == `cache_read_tokens` in the `PendingBilling` row == `cache_read_tokens` in every downstream table.

## Behavioural Example (coefficient = 0.5)

| Field | Raw upstream | After coefficient | Used in |
|-------|--------------|-------------------|---------|
| `input_tokens` | 1000 | 500 | SSE, PendingBilling, RequestLog, UsageRecord |
| `cache_read_input_tokens` | 8000 | **8000** (raw) | SSE, PendingBilling, RequestLog, UsageRecord |
| `cache_creation_input_tokens` | 500 | 250 | SSE, PendingBilling, RequestLog, UsageRecord |
| `output_tokens` | 200 | 100 | SSE, PendingBilling, RequestLog, UsageRecord |

At `coefficient = 1.0` all four fields are byte-identical to upstream and to each other (no rewrite in the SSE event).

## Error Handling

Unchanged from the original spec. The two pure functions preserve all short-circuits (`coefficient == 1.0`), all pass-through paths (unparseable data lines, non-dict `usage`, missing fields), and the `AdjustedUsage` dataclass remains the single source of truth for both the SSE response and the `PendingBilling` write.

| Scenario | Behaviour |
|----------|-----------|
| Coefficient = 1.0 | Short-circuit; SSE rewrite is byte-identical to upstream. `cache_read` is unaffected regardless. |
| SSE `data:` JSON unparseable | Pass the line through unchanged; log warning; never break the stream. |
| `usage` absent or non-dict | Pass through unchanged. |
| `cache_read_input_tokens` present in usage | Pass through unchanged (no longer in `USAGE_FIELDS`). |
| Coefficient ≤ 0 or > 1 | Pydantic 422 (admin). |
| Coefficient invalid float (NaN, Inf) | Pydantic 422. |
| Global row missing at request time | Service falls back to `1.0` and logs a one-time warning. |
| Admin write → cache stale | `invalidate()` called inside the same handler after commit. |
| Provider error mid-stream | Existing error path; coefficient is irrelevant. |
| `apply_coefficient` called with non-int token | TypeError; tests catch this. |

## Testing

### Backend unit tests

- `test_apply_coefficient.py`:
  - **New**: `test_cache_read_passthrough` — coefficient = 0.5, raw cache_read = 8000, expected 8000 in result; other three fields are `ceil(raw * 0.5)`.
  - **New**: `test_cache_read_passthrough_parameterised` — coefficients ∈ {0.1, 0.33, 0.5, 0.99} all leave `cache_read_tokens` unchanged.
  - **Adjust**: any existing test that multiplied `cache_read_tokens` by coefficient in its expected value.
  - Keep: `coefficient=1.0` short-circuit test (all four fields unchanged, including `cache_read`).
  - Keep: per-field independence test, but for the three discounted fields only.

- `test_sse_rewrite.py`:
  - **New**: `test_cache_read_passthrough_in_message_start` — build a full usage dict, apply 0.5, parse, assert `cache_read_input_tokens` unchanged.
  - **New**: `test_cache_read_passthrough_in_message_delta` — same for delta event.
  - **Adjust**: any existing test that expected `cache_read_input_tokens` to be adjusted.
  - Keep: `ping` event passthrough, unparseable data line, multi-line event.

- `test_token_coefficient_service.py`: no change — service does not know about per-field behaviour.

### Backend integration tests

- `test_billing_with_coefficient.py` (existing): update any seed data that assumed `cache_read_tokens` is discounted. The new expectation: `PendingBilling.cache_read_tokens == raw`; `RequestLog`, `BillingRecord`, `UsageRecord` all show raw `cache_read_tokens`; `BillingRecord.amount_cents` reflects the cost of `input_tokens + cache_creation_tokens + output_tokens` discounted and `cache_read_tokens` at full price.
- `test_proxy_response_with_coefficient.py` (existing): update the assertion for the SSE chunk — `cache_read_input_tokens` is byte-identical to the mock upstream's value; the other three are `ceil(raw * coefficient)`.
- Add a new end-to-end case: `coefficient=0.5`, mock upstream that returns `cache_read_input_tokens=1000`. The response SSE carries `1000`; the persisted `PendingBilling.cache_read_tokens` is `1000`.

### Frontend tests

- `DiscountsPage.test.tsx`:
  - **New**: assert the global help text mentions the three in-scope fields and explicitly excludes cache read.
  - **New**: open the per-model override dialog; assert the same hint is visible.
  - Existing tests: unchanged (form behaviour, save, validation).

### Manual smoke

- Set global to `0.5`. Send a `POST /v1/messages` that the mock returns `input=1000, cache_read=8000, cache_creation=500, output=200` for. Assert:
  - SSE `message_start` event: `input=500, cache_read=8000, cache_creation=250, output=100`.
  - DB `PendingBilling` row: same four values.
  - DB `UsageRecord`: same four values.
  - DB `BillingRecord.amount_cents` matches `compute_cost({input=500, cache_creation=250, output=100, cache_read=8000}, prices)`.
- Set model-level override to `0.1` on a model that has cache hits; confirm the same shape (only the three in-scope fields discounted).
- Set coefficient to `1.0`; confirm SSE is byte-identical to upstream for all four fields.

## Out-of-Scope (Future)

- Per-token-type coefficient with admin-configurable rates per field — would require a schema change (4 floats or JSON column) and UI expansion. Explicitly rejected for this iteration; revisit if operators ask for "give cache reads a separate discount knob".
- Coefficient > 1 (markup) — easy to add by relaxing the validator; unchanged from the original spec.
- Per-user / per-user-group coefficient — needs a join through `users` or `user_groups`; unchanged.
- Audit log of coefficient changes — table already records `updated_by` and `updated_at`; unchanged.
- Caching with TTL instead of invalidate-on-write; unchanged.

## Migration

None. The single `coefficient float` column on `token_coefficient_configs` is unchanged. No rows need updating. The next request after deployment picks up the new behaviour automatically (the in-memory cache is loaded at process start; rolling restart picks it up; no DB writes required).

## Compatibility

- **API contract**: `TokenCoefficient*` schemas, admin endpoints, and the response from `GET /api/admin/token-coefficients` are unchanged. No client of the admin API needs updating.
- **SSE protocol**: still Anthropic-compatible. The four `usage` fields are still present, but `cache_read_input_tokens` is now the raw upstream value. This is observable by API consumers — if any consumer computed "discount rate" from `cache_read_input_tokens`, that number will appear closer to 1.0 after this change. (No consumer in the codebase does this; the field is treated as opaque by all gateway-side code.)
- **Billing math**: `compute_cost` reads the four `PendingBilling.*_tokens` values and multiplies by per-model prices. The price for `cache_read_tokens` (per-1K-token cost) is unchanged; only the input value to that multiplication is now raw instead of discounted. The end-user cost shifts upward for cache-heavy workloads.
- **Frontend**: admin UI help text is the only visible change.

## Implementation Notes

Implementation plan: `docs/superpowers/plans/2026-06-21-token-coefficient-cache-read-passthrough-plan.md` (to be created via `writing-plans`).

Expected diff size: ~30 lines of code change + ~80 lines of test additions/updates + 1 spec delta. Touches:

- `backend/app/services/billing/token_coefficient.py` (1 line + 1 docstring)
- `backend/app/services/streaming/sse_rewrite.py` (1 line + 1 docstring)
- `frontend/app/admin/discounts/page.tsx` (~6 lines, two new help text strings)
- `backend/tests/services/billing/test_apply_coefficient.py` (2 new tests, adjust existing)
- `backend/tests/services/streaming/test_sse_rewrite.py` (2 new tests, adjust existing)
- `frontend/tests/admin/DiscountsPage.test.tsx` (1–2 new assertions)
- `docs/superpowers/specs/2026-06-09-token-coefficient-design.md` (delta edits to §Summary, §Non-Goals, §Changes §7, §Changes §8, §Out-of-Scope)
- `docs/superpowers/specs/2026-06-21-token-coefficient-cache-read-passthrough-design.md` (this file)

Not touched: `proxy.py`, `admin_token_coefficients.py`, `token_coefficient_service.py`, `TokenCoefficientConfig` ORM, Alembic migrations, `frontend/lib/api/admin/token-coefficients.ts`, the discount page table structure, `pending.py` / `settle.py` / `compute_cost` / billing tables.

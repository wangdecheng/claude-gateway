# Token Coefficient — cache_read Pass-Through Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify the admin token coefficient (discount) feature so that `cache_read_input_tokens` is passed through at the raw upstream value, while `input_tokens`, `cache_creation_input_tokens`, and `output_tokens` continue to be multiplied by `ceil(raw * coefficient)`. No DB / API / UI surface change beyond a one-line help text addition; the change is localised to two pure functions and their tests.

**Architecture:** Single admin coefficient (already approved for the original feature) is unchanged. The `apply_coefficient()` pure function in `backend/app/services/billing/token_coefficient.py` and the `USAGE_FIELDS` tuple in `backend/app/services/streaming/sse_rewrite.py` are the only production code changes. The proxy call sites, the service resolution path, the admin router, the ORM, and the migrations are untouched. Test files and the original spec are updated as a delta.

**Tech Stack:** Python 3.14 / FastAPI / pytest; Next.js 15 / React 19 / vitest / @testing-library.

**Spec:** [`docs/superpowers/specs/2026-06-21-token-coefficient-cache-read-passthrough-design.md`](../specs/2026-06-21-token-coefficient-cache-read-passthrough-design.md)

**Existing reference spec (to receive a delta edit, NOT replaced):** [`docs/superpowers/specs/2026-06-09-token-coefficient-design.md`](../specs/2026-06-09-token-coefficient-design.md)

---

## File Structure

**Modified (production):**
- `backend/app/services/billing/token_coefficient.py` — `apply_coefficient()` skips `cache_read_tokens`; module docstring rewritten.
- `backend/app/services/streaming/sse_rewrite.py` — `USAGE_FIELDS` drops `cache_read_input_tokens`; module docstring rewritten.

**Modified (tests):**
- `backend/tests/services/billing/test_apply_coefficient.py` — 2 new tests + updates to 3 existing tests.
- `backend/tests/services/test_sse_rewrite.py` — 2 new tests + updates to 1 existing test.
- `backend/tests/test_proxy_response_with_coefficient.py` — update 2 assertions (cache_read is raw).
- `frontend/tests/app/admin/discounts/page.test.tsx` — 2 new assertions (help text).

**Modified (frontend UI):**
- `frontend/app/admin/discounts/page.tsx` — add help text strings (2 locations).

**Modified (docs):**
- `docs/superpowers/specs/2026-06-09-token-coefficient-design.md` — delta edits to §Summary, §Non-Goals, §Changes §7 (USAGE_FIELDS + apply_coefficient example), §Changes §8 (proxy examples), §Out-of-Scope.

**Not modified (deliberately):** `backend/app/routers/proxy.py`, `backend/app/routers/admin_token_coefficients.py`, `backend/app/services/token_coefficient_service.py`, `backend/app/models/token_coefficient.py`, `backend/alembic/versions/*`, `frontend/lib/api/admin/token-coefficients.ts`.

---

## Task 1: Update `apply_coefficient()` to pass `cache_read_tokens` through

**Files:**
- Modify: `backend/app/services/billing/token_coefficient.py:1-46` (full file rewrite)
- Test: `backend/tests/services/billing/test_apply_coefficient.py`

- [ ] **Step 1.1: Write the failing test (TDD: assert cache_read passes through)**

Append the following two tests to `backend/tests/services/billing/test_apply_coefficient.py` (do not remove existing tests yet — that is Task 2):

```python
def test_apply_coefficient_cache_read_passthrough():
    """cache_read_tokens is never multiplied by the coefficient."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=1000,
        cache_read_tokens=8000,
        cache_creation_tokens=500,
        output_tokens=200,
        coefficient=0.5,
    )
    # The three discounted fields are ceil(raw * 0.5):
    assert out.input_tokens == 500
    assert out.cache_creation_tokens == 250
    assert out.output_tokens == 100
    # cache_read is the raw value, untouched:
    assert out.cache_read_tokens == 8000


def test_apply_coefficient_cache_read_passthrough_at_various_coefficients():
    """cache_read passes through for any coefficient in (0, 1]."""
    import pytest
    from app.services.billing.token_coefficient import apply_coefficient

    for coef in (0.1, 0.33, 0.5, 0.99, 1.0):
        out = apply_coefficient(
            input_tokens=10,
            cache_read_tokens=12345,
            cache_creation_tokens=10,
            output_tokens=10,
            coefficient=coef,
        )
        assert out.cache_read_tokens == 12345, f"coef={coef}"
```

- [ ] **Step 1.2: Run the new tests to verify they fail**

Run: `cd backend && uv run pytest tests/services/billing/test_apply_coefficient.py::test_apply_coefficient_cache_read_passthrough tests/services/billing/test_apply_coefficient.py::test_apply_coefficient_cache_read_passthrough_at_various_coefficients -v`

Expected: FAIL with `AssertionError: assert 8000 == 4000` (current code multiplies cache_read by 0.5).

- [ ] **Step 1.3: Modify `apply_coefficient()` and the module docstring**

Edit `backend/app/services/billing/token_coefficient.py`. Replace the entire file contents with:

```python
"""Pure helpers for applying the admin-configured token coefficient (discount).

The coefficient is a float in (0, 1]; it is multiplied with three of the four
Anthropic token fields — `input_tokens`, `cache_creation_input_tokens` (cache
write), and `output_tokens`. The fourth field, `cache_read_input_tokens`, is
**not** discounted: it is passed through at the raw upstream value. The reason
is that upstream providers (Anthropic, DeepSeek) already discount cache reads
heavily, and stacking the gateway-level discount on top of an already-cheap
field offers little benefit. Input tokens and cache writes, by contrast, carry
the full upstream cost.

Each discounted field is rounded up with ``math.ceil`` so a 0.5x coefficient
never rounds below half a token.

The same AdjustedUsage is the source of truth for both the SSE response
(rewritten via sse_rewrite._apply_coefficient_to_sse_event) and the
PendingBilling write in proxy.billing_stream — so what the user sees in the
response is exactly what they are billed for.
"""

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

- [ ] **Step 1.4: Run the new tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/billing/test_apply_coefficient.py::test_apply_coefficient_cache_read_passthrough tests/services/billing/test_apply_coefficient.py::test_apply_coefficient_cache_read_passthrough_at_various_coefficients -v`

Expected: PASS (2 passed).

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/services/billing/token_coefficient.py backend/tests/services/billing/test_apply_coefficient.py
git commit -m "feat(billing): pass cache_read through token coefficient unchanged"
```

---

## Task 2: Update existing `apply_coefficient` tests to reflect new behaviour

**Files:**
- Modify: `backend/tests/services/billing/test_apply_coefficient.py` (3 tests)

- [ ] **Step 2.1: Update `test_apply_coefficient_half_ceil_boundary`**

In `backend/tests/services/billing/test_apply_coefficient.py`, replace the body of `test_apply_coefficient_half_ceil_boundary` (the function still exists from Task 1; we update its assertions for the new behaviour):

```python
def test_apply_coefficient_half_ceil_boundary():
    """7 * 0.5 = 3.5 -> ceil = 4.  8 * 0.5 = 4.0 -> ceil = 4.
    cache_read is NOT discounted, so the raw value 8 stays 8 (not 4)."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=7,
        cache_read_tokens=8,
        cache_creation_tokens=1,
        output_tokens=0,
        coefficient=0.5,
    )
    assert out.input_tokens == 4
    assert out.cache_read_tokens == 8   # was 4; now pass-through
    assert out.cache_creation_tokens == 1
    assert out.output_tokens == 0
```

- [ ] **Step 2.2: Update `test_apply_coefficient_third_rounds_up`**

In the same file, replace the body of `test_apply_coefficient_third_rounds_up`:

```python
def test_apply_coefficient_third_rounds_up():
    """1 * 0.33 = 0.33 -> ceil = 1. cache_read is NOT discounted (raw = 2)."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=1,
        cache_read_tokens=2,
        cache_creation_tokens=3,
        output_tokens=4,
        coefficient=0.33,
    )
    assert out.input_tokens == 1
    assert out.cache_read_tokens == 2   # was 1; now pass-through
    assert out.cache_creation_tokens == 1
    assert out.output_tokens == 2
```

- [ ] **Step 2.3: Update `test_apply_coefficient_zero_inputs_stay_zero`**

In the same file, replace the body of `test_apply_coefficient_zero_inputs_stay_zero` (the assertion is unchanged in spirit — zero stays zero — but keep the file consistent with the new behaviour):

```python
def test_apply_coefficient_zero_inputs_stay_zero():
    """Zero token counts stay zero under any coefficient."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=0,
        coefficient=0.1,
    )
    assert out.input_tokens == 0
    assert out.cache_read_tokens == 0
    assert out.cache_creation_tokens == 0
    assert out.output_tokens == 0
```

- [ ] **Step 2.4: Run the full test file**

Run: `cd backend && uv run pytest tests/services/billing/test_apply_coefficient.py -v`

Expected: PASS (all 6 tests, including the 2 added in Task 1 and the 3 updated here, plus the unchanged `test_apply_coefficient_1_returns_same_values` and `test_apply_coefficient_fields_are_independent`).

- [ ] **Step 2.5: Commit**

```bash
git add backend/tests/services/billing/test_apply_coefficient.py
git commit -m "test(billing): update apply_coefficient tests for cache_read passthrough"
```

---

## Task 3: Update SSE rewrite `USAGE_FIELDS` and tests

**Files:**
- Modify: `backend/app/services/streaming/sse_rewrite.py:1-78`
- Test: `backend/tests/services/test_sse_rewrite.py`

- [ ] **Step 3.1: Write the failing test (TDD: SSE rewrite leaves cache_read alone)**

Append the following two tests to `backend/tests/services/test_sse_rewrite.py`:

```python
def test_rewrite_cache_read_passthrough_in_message_start():
    """message_start with full usage — cache_read_input_tokens is raw;
    the other three fields are ceil(raw * 0.5)."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1","usage":{'
            '"input_tokens":100,"cache_read_input_tokens":80,'
            '"cache_creation_input_tokens":20,"output_tokens":0}}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # Discounted: 100*0.5=50, 20*0.5=10, 0*0.5=0
    assert '"input_tokens":50' in out
    assert '"cache_creation_input_tokens":10' in out
    assert '"output_tokens":0' in out
    # Pass-through: 80 stays 80
    assert '"cache_read_input_tokens":80' in out
    # Make sure the original discounted value is NOT present:
    assert '"cache_read_input_tokens":40' not in out


def test_rewrite_cache_read_passthrough_in_message_delta():
    """message_delta may re-emit cache_read_input_tokens; it must stay raw."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_delta",
            'data: {"type":"message_delta","usage":{'
            '"output_tokens":7,"cache_read_input_tokens":1234}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # 7 * 0.5 = 3.5 -> 4
    assert '"output_tokens":4' in out
    # Pass-through
    assert '"cache_read_input_tokens":1234' in out
    assert '"cache_read_input_tokens":617' not in out
```

- [ ] **Step 3.2: Run the new tests to verify they fail**

Run: `cd backend && uv run pytest tests/services/test_sse_rewrite.py::test_rewrite_cache_read_passthrough_in_message_start tests/services/test_sse_rewrite.py::test_rewrite_cache_read_passthrough_in_message_delta -v`

Expected: FAIL with `AssertionError: assert '"cache_read_input_tokens":80' in <output>` (current code rewrites cache_read to 40).

- [ ] **Step 3.3: Modify `USAGE_FIELDS` and the module docstring**

Edit `backend/app/services/streaming/sse_rewrite.py`. Replace the entire file contents with:

```python
"""SSE event rewriting — apply the admin token coefficient to usage fields.

This is a pure function: it takes a single SSE event string and a coefficient,
and returns the event with the `usage` block in any `data:` line rewritten so
that the three discounted Anthropic token fields are multiplied by the
coefficient (ceil). The fourth field, `cache_read_input_tokens`, is **not**
discounted — it is passed through at the raw upstream value. See
`app.services.billing.token_coefficient` for the rationale.

Behaviour:
- Non-data lines (`event:`, `id:`, comments) are passed through unchanged.
- A data: line whose payload is unparseable JSON is passed through unchanged.
- A data: line whose payload has no `usage` dict, or where `usage` is not a
  dict, is passed through unchanged.
- `usage` may live at the top level (e.g. `message_delta`) or nested inside
  `message` (e.g. `message_start` per the Anthropic SSE schema).
- coefficient=1.0 short-circuits and returns the event byte-identically.
"""

import json
import math

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


def _rewrite_usage_in_place(obj: dict, coefficient: float) -> bool:
    """Look for a `usage` dict at `obj["usage"]` or `obj["message"]["usage"]`.
    If found, rewrite it in place. Returns True if a rewrite occurred.
    """
    rewrote = False
    if isinstance(obj.get("usage"), dict):
        obj["usage"] = _apply_coefficient_to_usage_dict(obj["usage"], coefficient)
        rewrote = True
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        msg["usage"] = _apply_coefficient_to_usage_dict(msg["usage"], coefficient)
        rewrote = True
    return rewrote


def _apply_coefficient_to_sse_event(event: str, coefficient: float) -> str:
    """Rewrite a single SSE event so that any data: line whose payload contains
    a 'usage' dict has its discounted token counts multiplied by `coefficient`
    (ceil). `cache_read_input_tokens` is left at its raw upstream value."""
    if coefficient == 1.0:
        return event
    lines = event.split("\n")
    out_lines: list[str] = []
    for line in lines:
        if not line.startswith("data:"):
            out_lines.append(line)
            continue
        payload = line[len("data:") :].lstrip()
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            out_lines.append(line)
            continue
        if not isinstance(obj, dict):
            out_lines.append(line)
            continue
        if not _rewrite_usage_in_place(obj, coefficient):
            out_lines.append(line)
            continue
        out_lines.append("data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)
```

(Note the final `return` is `"\\n".join(out_lines)` — confirm the closing parenthesis is on the right line; the Python file's actual return statement is `return "\\n".join(out_lines)`. Replace exactly with the value above; the indentation of the final `return` is preserved.)

- [ ] **Step 3.4: Run the new tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_sse_rewrite.py::test_rewrite_cache_read_passthrough_in_message_start tests/services/test_sse_rewrite.py::test_rewrite_cache_read_passthrough_in_message_delta -v`

Expected: PASS (2 passed).

- [ ] **Step 3.5: Update `test_rewrite_message_start_adjusts_all_four_fields`**

In `backend/tests/services/test_sse_rewrite.py`, replace the body of `test_rewrite_message_start_adjusts_all_four_fields` (note the function name will read as a lie under the new behaviour, so we also rename it — leave the function name unchanged for git diff minimality, but adjust the assertions):

```python
def test_rewrite_message_start_adjusts_three_fields():
    """message_start with full usage — three fields adjusted, cache_read is raw."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1","usage":{'
            '"input_tokens":100,"cache_read_input_tokens":80,'
            '"cache_creation_input_tokens":20,"output_tokens":0}}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # input: 100*0.5=50.0 -> 50; cache_creation: 20*0.5=10.0 -> 10; output: 0*0.5=0.0 -> 0
    assert '"input_tokens":50' in out
    assert '"cache_creation_input_tokens":10' in out
    assert '"output_tokens":0' in out
    # cache_read is pass-through: 80 stays 80
    assert '"cache_read_input_tokens":80' in out
    assert '"cache_read_input_tokens":40' not in out
```

- [ ] **Step 3.6: Run the full test file**

Run: `cd backend && uv run pytest tests/services/test_sse_rewrite.py -v`

Expected: PASS (all tests, including the 2 new passthrough tests from Step 3.1, the 1 updated `test_rewrite_message_start_adjusts_three_fields` from Step 3.5, plus the unchanged `test_rewrite_message_delta_only_adjusts_output`, `test_rewrite_ping_event_unchanged`, `test_rewrite_unparseable_data_line_unchanged`, `test_rewrite_usage_non_dict_unchanged`, `test_rewrite_coefficient_1_short_circuits`, `test_rewrite_preserves_non_data_lines`).

- [ ] **Step 3.7: Commit**

```bash
git add backend/app/services/streaming/sse_rewrite.py backend/tests/services/test_sse_rewrite.py
git commit -m "feat(streaming): drop cache_read from SSE coefficient rewrite"
```

---

## Task 4: Update the end-to-end proxy test to expect raw `cache_read`

**Files:**
- Modify: `backend/tests/test_proxy_response_with_coefficient.py:140-145` and `:170-173`

- [ ] **Step 4.1: Update `test_response_usage_is_adjusted`**

In `backend/tests/test_proxy_response_with_coefficient.py`, replace the assertions block at the end of `test_response_usage_is_adjusted` (lines 140–145) with:

```python
    # message_start usage: input 100*0.5=50, cache_creation 20*0.5=10;
    # cache_read is pass-through: 80 stays 80
    assert '"input_tokens":50' in body
    assert '"cache_read_input_tokens":80' in body
    assert '"cache_creation_input_tokens":10' in body
    # message_delta: output 7*0.5=3.5 -> ceil=4
    assert '"output_tokens":4' in body
```

- [ ] **Step 4.2: Update `test_pending_billing_stores_adjusted_values`**

In the same file, replace the assertions block at the end of `test_pending_billing_stores_adjusted_values` (lines 170–173) with:

```python
        assert pb.input_tokens == 50
        assert pb.cache_read_tokens == 80   # pass-through: raw upstream value
        assert pb.cache_creation_tokens == 10
        assert pb.output_tokens == 4
```

- [ ] **Step 4.3: Run the test file**

Run: `cd backend && uv run pytest tests/test_proxy_response_with_coefficient.py -v`

Expected: PASS (2 passed).

- [ ] **Step 4.4: Commit**

```bash
git add backend/tests/test_proxy_response_with_coefficient.py
git commit -m "test(proxy): assert cache_read stays raw through the SSE/PendingBilling pipeline"
```

---

## Task 5: Add help text to the discounts page

**Files:**
- Modify: `frontend/app/admin/discounts/page.tsx:108-110` and `:217` (one paragraph + one label)

- [ ] **Step 5.1: Locate the existing global help text**

Open `frontend/app/admin/discounts/page.tsx`. The current global help text (around line 108–110) is:

```tsx
<p className="mt-1 text-xs text-slate-500">
  所有模型的默认折扣系数（0 &lt; x ≤ 1）。1.0 表示无折扣。
</p>
```

- [ ] **Step 5.2: Replace the global help text**

Edit `frontend/app/admin/discounts/page.tsx`. Replace the three-line block above with:

```tsx
<p className="mt-1 text-xs text-slate-500">
  所有模型的默认折扣系数（0 &lt; x ≤ 1）。1.0 表示无折扣。
  作用于 <code>input_tokens</code>、<code>cache_creation_input_tokens</code>、<code>output_tokens</code>；
  <code>cache_read_input_tokens</code> 不参与折扣。
</p>
```

- [ ] **Step 5.3: Locate the per-model dialog label**

In the same file, find the per-model dialog's input block. The current label (around line 217) is:

```tsx
<Label htmlFor="model-coefficient">系数 (0 &lt; x ≤ 1)</Label>
```

- [ ] **Step 5.4: Add help text under the per-model input**

Replace the existing label + input block:

```tsx
<div className="space-y-2">
  <Label htmlFor="model-coefficient">系数 (0 &lt; x ≤ 1)</Label>
  <Input
    id="model-coefficient"
    type="number"
    step="0.01"
    min="0.01"
    max="1"
    value={editing?.draft ?? ""}
    onChange={(e) =>
      editing && setEditing({ ...editing, draft: e.target.value, error: null })
    }
  />
  {editing?.error && (
    <p className="text-xs text-red-600">{editing.error}</p>
  )}
</div>
```

with:

```tsx
<div className="space-y-2">
  <Label htmlFor="model-coefficient">系数 (0 &lt; x ≤ 1)</Label>
  <Input
    id="model-coefficient"
    type="number"
    step="0.01"
    min="0.01"
    max="1"
    value={editing?.draft ?? ""}
    onChange={(e) =>
      editing && setEditing({ ...editing, draft: e.target.value, error: null })
    }
  />
  <p className="text-xs text-slate-500">
    作用于 <code>input_tokens</code>、<code>cache_creation_input_tokens</code>、<code>output_tokens</code>；
    <code>cache_read_input_tokens</code> 不参与折扣。
  </p>
  {editing?.error && (
    <p className="text-xs text-red-600">{editing.error}</p>
  )}
</div>
```

- [ ] **Step 5.5: Run lint**

Run: `cd frontend && npm run lint 2>&1 | tail -20`

Expected: PASS (no errors). If there are pre-existing lint errors unrelated to this file, ignore them.

- [ ] **Step 5.6: Commit**

```bash
git add frontend/app/admin/discounts/page.tsx
git commit -m "feat(admin): explain which token fields the coefficient applies to"
```

---

## Task 6: Add frontend tests for the new help text

**Files:**
- Modify: `frontend/tests/app/admin/discounts/page.test.tsx`

- [ ] **Step 6.1: Add an assertion that the global help text mentions the in-scope fields**

Open `frontend/tests/app/admin/discounts/page.test.tsx`. Find the test `it("renders the global coefficient value and a model list", ...)` (lines 48–61). Append the following assertion to the end of that test (before the closing `});`):

```tsx
    // Help text must mention the three in-scope fields and exclude cache_read
    expect(
      screen.getByText(/cache_read_input_tokens\s*不参与折扣/)
    ).toBeInTheDocument();
    expect(screen.getByText(/input_tokens/)).toBeInTheDocument();
    expect(screen.getByText(/cache_creation_input_tokens/)).toBeInTheDocument();
    expect(screen.getByText(/output_tokens/)).toBeInTheDocument();
```

- [ ] **Step 6.2: Add a new test for the per-model dialog help text**

In the same file, append a new `it(...)` block at the end of the `describe("DiscountsPage", ...)` block (before its closing `});`):

```tsx
  it("shows the same field-scope hint in the per-model dialog", async () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 1.0,
        globalMeta: { coefficient: 1.0, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [],
      },
      isLoading: false,
    });
    renderWithQuery(<DiscountsPage />);
    const user = userEvent.setup();
    // Open the per-model override dialog (button label is "设置覆盖" when none)
    await user.click(screen.getAllByRole("button", { name: /设置覆盖/ })[0]);
    // The dialog carries the same help text:
    expect(
      await screen.findByText(/cache_read_input_tokens\s*不参与折扣/)
    ).toBeInTheDocument();
  });
```

- [ ] **Step 6.3: Run the test file**

Run: `cd frontend && npm test -- tests/app/admin/discounts/page.test.tsx 2>&1 | tail -30`

Expected: PASS (4 tests: 3 existing + 1 new global-hint assertion merged into the first test + 1 new dialog test = 5 assertions across 4 tests).

- [ ] **Step 6.4: Commit**

```bash
git add frontend/tests/app/admin/discounts/page.test.tsx
git commit -m "test(admin): assert discounts page help text names the in-scope fields"
```

---

## Task 7: Apply the delta edits to the original 2026-06-09 spec

**Files:**
- Modify: `docs/superpowers/specs/2026-06-09-token-coefficient-design.md`

- [ ] **Step 7.1: Edit §Summary**

In `docs/superpowers/specs/2026-06-09-token-coefficient-design.md`, replace the current Summary paragraph (line 8) with:

```markdown
## Summary

Let admin multiply the `input_tokens` / `cache_creation_input_tokens` / `output_tokens` values returned to API clients (and used for billing) by a single coefficient in `(0, 1]`. Apply globally by default, with optional per-model overrides. Used to grant token discounts without touching upstream integration or per-model pricing.

**Note (2026-06-21):** `cache_read_input_tokens` is **not** discounted — it is passed through at the raw upstream value. See [`2026-06-21-token-coefficient-cache-read-passthrough-design.md`](2026-06-21-token-coefficient-cache-read-passthrough-design.md) for the rationale and behaviour change.
```

- [ ] **Step 7.2: Edit §Non-Goals**

Find the bullet:

```markdown
- Per-token-type coefficients (input vs cache_read vs output) — single coefficient covers all four fields.
```

Replace it with:

```markdown
- Per-token-type coefficients — single coefficient covers all three discounted fields. (Per the 2026-06-21 delta spec, `cache_read_input_tokens` is excluded from the discount; this is a scope narrowing, not a per-field coefficient knob.)
```

- [ ] **Step 7.3: Edit §Changes §7 — the `USAGE_FIELDS` example**

Find the `USAGE_FIELDS` tuple in §7 (around lines 188–194):

```python
USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)
```

Replace with:

```python
USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)
```

- [ ] **Step 7.4: Edit §Changes §7 — the `apply_coefficient` example**

Find the `apply_coefficient` function body in §7 (around lines 162–180). Replace the `AdjustedUsage(...)` return inside the non-1.0 branch (lines 175–180) with:

```python
    return AdjustedUsage(
        input_tokens=math.ceil(input_tokens * coefficient),
        cache_read_tokens=cache_read_tokens,  # pass-through: cache read not discounted
        cache_creation_tokens=math.ceil(cache_creation_tokens * coefficient),
        output_tokens=math.ceil(output_tokens * coefficient),
    )
```

- [ ] **Step 7.5: Edit §Changes §8 — the streaming loop example comment**

In §Changes §8, find the inline comment above `yield _apply_coefficient_to_sse_event(chunk, coefficient)` (around line 252) and replace it with:

```python
    # NEW: rewrite usage in the chunk before yielding to the client.
    # cache_read_input_tokens is left at its raw upstream value (no discount).
    yield _apply_coefficient_to_sse_event(chunk, coefficient)
```

- [ ] **Step 7.6: Edit §Out-of-Scope**

Find the bullet:

```markdown
- Per-token-type coefficient — would extend the row to 4 floats or add separate fields.
```

Replace with:

```markdown
- Per-token-type coefficient — would extend the row to 3 floats or add separate fields. (See 2026-06-21 delta spec for the cache_read exclusion, which is a scope narrowing rather than a per-field coefficient system.)
```

- [ ] **Step 7.7: Commit**

```bash
git add -f docs/superpowers/specs/2026-06-09-token-coefficient-design.md
git commit -m "docs(spec): apply 2026-06-21 delta to token coefficient spec (cache_read passthrough)"
```

---

## Task 8: Run the full test suite and confirm green

**Files:** none (verification only)

- [ ] **Step 8.1: Run backend tests**

Run: `cd backend && uv run pytest -v 2>&1 | tail -50`

Expected: PASS — all tests pass. The four files we touched (token_coefficient, sse_rewrite, test_apply_coefficient, test_sse_rewrite, test_proxy_response_with_coefficient) all pass; no other test files are affected.

- [ ] **Step 8.2: Run frontend tests**

Run: `cd frontend && npm test 2>&1 | tail -30`

Expected: PASS — all vitest tests pass, including the 5 DiscountsPage assertions.

- [ ] **Step 8.3: Run backend lint**

Run: `cd backend && uv run ruff check . 2>&1 | tail -20`

Expected: PASS (no new lint errors). The two source files we touched were already in the project; no new patterns introduced. The `sys.path.insert` in the touched test files is pre-existing and consistent with the rest of the suite (see original spec's "Deviations" note).

- [ ] **Step 8.4: Run frontend lint**

Run: `cd frontend && npm run lint 2>&1 | tail -20`

Expected: PASS (no new lint errors). Pre-existing errors in unrelated files are out of scope.

- [ ] **Step 8.5: Final commit if any incidental cleanup is needed**

If any of the above surfaced an incidental fix (e.g. an unused import), commit it now:

```bash
git add -A
git commit -m "chore: post-test cleanup"  # only if a non-empty diff exists
```

If no diff, skip this step.

---

## Self-Review

**Spec coverage check (against `2026-06-21-token-coefficient-cache-read-passthrough-design.md`):**

- §Summary → covered by Task 1 (impl) + Task 7 (spec delta).
- §Goals — `cache_read` raw; other three discounted; SSE == billing; 1.0 short-circuit; no migration → covered by Tasks 1, 3, 4, 8.
- §Non-Goals — "no per-field coefficients", "no DB schema change", "no API/UI change", "no historical backfill", "no new column" → confirmed by zero-touch on those areas; only a one-line help text added (allowed by §Decisions row "Admin UI hint" and §Changes §4).
- §Decisions — "Which fields are discounted" → Tasks 1 + 3. "Coefficient value range" → no change. "Data model" → no change. "Rounding" → no change. "Where to apply" → no change. "Admin UI hint" → Task 5. "Historical backfill" → Task 8 confirms no migration.
- §Changes — §1 → Task 1. §2 → Task 3. §3 → confirmed no change. §4 → Task 5. §5 → Tasks 2, 3, 4, 6. §6 → Task 7.
- §Data Flow → covered by Tasks 1, 3, 4 (the proxy code path is unchanged; the behaviour is updated by the pure functions and asserted in tests).
- §Behavioural Example → asserted by `test_apply_coefficient_cache_read_passthrough` (Task 1) and `test_rewrite_cache_read_passthrough_in_message_start` (Task 3) using the exact raw values from the spec example.
- §Error Handling — short-circuit, unparseable, missing usage, coefficient range, etc. → unchanged behaviour; existing tests in `test_sse_rewrite.py` (Steps 3.6) and `test_apply_coefficient.py` (Step 2.4) cover them.
- §Testing — backend unit tests (Tasks 1, 2, 3) → covered. Backend integration tests (Task 4) → covered. Frontend tests (Task 6) → covered. Manual smoke → out of scope for the implementation plan; the developer should run the smoke after deploy.
- §Out-of-Scope (Future) → no implementation needed; spec is informative.
- §Migration → "None" — Task 8 confirms no migration script touched.
- §Compatibility → documented in spec; no code change needed.
- §Implementation Notes — file list → matches Tasks 1–7.

**Placeholder scan:** No TBD / TODO / "implement later" / "fill in details" in any task. Each code step has the actual replacement code. Each test step has the actual test code.

**Type / signature consistency:**
- `apply_coefficient(...)` signature unchanged in Tasks 1 and 2.
- `AdjustedUsage` dataclass unchanged.
- `USAGE_FIELDS` constant referenced by name in Task 3 — same name, same type, same scope.
- `_apply_coefficient_to_sse_event(event, coefficient)` signature unchanged in Task 3.
- Frontend `useTokenCoefficients`, `useUpdateGlobalCoefficient`, `useUpsertModelCoefficient`, `useDeleteModelCoefficient` — not modified.
- Help text strings in Task 5 use the same wording the frontend test asserts in Task 6 (`cache_read_input_tokens\s*不参与折扣`, `input_tokens`, `cache_creation_input_tokens`, `output_tokens`).

**Cross-task consistency:**
- Task 1 uses `0.5` and `8000` for cache_read passthrough; Task 2 updates `test_apply_coefficient_half_ceil_boundary` with the same numbers (`8` raw, `0.5` coef, expects `8` not `4`); Task 3 uses the same raw values in its SSE rewrite tests; Task 4 mirrors them in the end-to-end assertion (raw 80, expects 80 not 40). The numerical contract is consistent across all tests.

**Potential issues to watch during execution:**
- Task 3.3 file replacement: the final `return "\n".join(out_lines)` line — ensure the closing parenthesis is on the correct line and the indentation matches the existing file (4 spaces).
- Task 5 edits two non-adjacent locations in the same file; commit them together as one logical change to keep the diff readable.
- Task 6.1 modifies an existing test rather than adding a new one; keep the change additive (append assertions before the closing `});`) to avoid disrupting other tests' snapshot-like behaviour.
- Task 7 edits a "Status: approved" spec — these are doc deltas, not status changes. The spec status stays "approved"; the body accumulates the 2026-06-21 note inline.

**Conclusion:** All spec requirements are covered by a task; no placeholders; all types and signatures are consistent across tasks. Plan is ready to execute.

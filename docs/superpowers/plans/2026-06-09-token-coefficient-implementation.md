# Token Coefficient (Discount) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable per-model token coefficient (discount) that admin can set globally or per-model; the same coefficient is applied to the Anthropic SSE response (rewriting usage in `message_start` / `message_delta` events) and to the `PendingBilling` write (so downstream `RequestLog` / `BillingRecord` / `UsageRecord` all see the adjusted values).

**Architecture:** New dedicated `token_coefficient_configs` table (global row + per-model overrides). A `TokenCoefficientService` loads rows into an in-memory dict on startup and exposes a synchronous `get_for_model(model_id)` lookup. The service is invalidated on any admin write. The proxy (`create_message` → inner `billing_stream` async function in `backend/app/routers/proxy.py`) calls the service once, rewrites each chunk with `_apply_coefficient_to_sse_event`, and applies `apply_coefficient` to the accumulated usage before `write_pending_billing`. The `BillingWorker` → `settle_one` chain is unchanged because `PendingBilling` already stores the adjusted tokens.

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy async / Alembic / Pydantic v2; Next.js 15 / React 19 / TanStack Query / Tailwind CSS 4; pytest (backend) and vitest (frontend).

---

## File Structure

### New files
| Path | Responsibility |
|------|----------------|
| `backend/alembic/versions/016_add_token_coefficient_configs.py` | Migration: create table + seed global row |
| `backend/app/models/token_coefficient.py` | `TokenCoefficientConfig` ORM model |
| `backend/app/schemas/token_coefficient.py` | Pydantic request/response schemas |
| `backend/app/services/token_coefficient_service.py` | Resolution + in-memory cache + `invalidate()` |
| `backend/app/services/billing/token_coefficient.py` | Pure function `apply_coefficient()` and `AdjustedUsage` |
| `backend/app/services/streaming/__init__.py` | Empty package marker |
| `backend/app/services/streaming/sse_rewrite.py` | Pure function `_apply_coefficient_to_sse_event()` and helper |
| `backend/app/routers/admin_token_coefficients.py` | Admin CRUD router |
| `backend/tests/services/billing/test_apply_coefficient.py` | Unit tests for `apply_coefficient` |
| `backend/tests/services/test_sse_rewrite.py` | Unit tests for SSE rewrite |
| `backend/tests/services/test_token_coefficient_service.py` | Unit tests for service resolution + cache |
| `backend/tests/test_admin_token_coefficients_router.py` | Integration tests for admin endpoints |
| `backend/tests/test_proxy_response_with_coefficient.py` | Integration tests for proxy SSE rewrite + settlement |
| `frontend/lib/api/admin/token-coefficients.ts` | API client + TanStack Query hooks |
| `frontend/app/admin/discounts/page.tsx` | Admin UI: global + per-model override |
| `frontend/tests/app/admin/discounts/page.test.tsx` | Vitest tests for the admin page |

### Modified files
| Path | Change |
|------|--------|
| `backend/app/models/__init__.py` | Export `TokenCoefficientConfig` (or re-export through `app.database.Base.metadata` — no change needed since `Base.metadata.create_all` picks up subclasses) |
| `backend/api/app.py` | Lifespan: instantiate `TokenCoefficientService`, call `.load()`, store on `app.state`. Register the new admin router. |
| `backend/app/routers/proxy.py` | In `create_message`: look up coefficient, rewrite each yielded chunk, apply coefficient to `accumulated_usage` in `finally` before `write_pending_billing`. |
| `frontend/app/admin/layout.tsx` | Add "折扣配置" nav link under "配置中心" group. |
| `frontend/app/admin/layout.tsx` | Import `Percent` icon from `lucide-react`. |

---

## Task 1: Database migration

**Files:**
- Create: `backend/alembic/versions/016_add_token_coefficient_configs.py`

- [ ] **Step 1: Create the migration file**

Write the following to `backend/alembic/versions/016_add_token_coefficient_configs.py`:

```python
"""add token_coefficient_configs table (global + per-model override) and seed default global row

Revision ID: 016
Revises: 015
Create Date: 2026-06-09
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "token_coefficient_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope_type", sa.String(10), nullable=False),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("models.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "coefficient",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("model_id", name="uq_token_coefficient_configs_model_id"),
        sa.CheckConstraint(
            "coefficient > 0 AND coefficient <= 1",
            name="ck_token_coefficient_configs_range",
        ),
        sa.CheckConstraint(
            "(scope_type = 'global' AND model_id IS NULL) OR "
            "(scope_type = 'model' AND model_id IS NOT NULL)",
            name="ck_token_coefficient_configs_scope_model",
        ),
    )
    # Seed default global row
    op.execute(
        "INSERT INTO token_coefficient_configs (scope_type, coefficient) "
        "VALUES ('global', 1.0)"
    )


def downgrade() -> None:
    op.drop_table("token_coefficient_configs")
```

- [ ] **Step 2: Verify migration applies cleanly**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run alembic upgrade head`
Expected: "Running upgrade 015 -> 016, add token_coefficient_configs table...". Inspect the table:
`uv run python -c "import sqlite3; c=sqlite3.connect('/tmp/cg_test.db'); ..."` — for the dev DB check the table exists. If running against the dev PostgreSQL, the upgrade will run the DDL inline.

- [ ] **Step 3: Verify downgrade is symmetric**

Run: `cd backend && uv run alembic downgrade -1`
Expected: "Running downgrade 016 -> 015...". Then re-upgrade: `uv run alembic upgrade head`. The table should be back with the seed row.

- [ ] **Step 4: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add -f backend/alembic/versions/016_add_token_coefficient_configs.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(db): add token_coefficient_configs migration"
```

---

## Task 2: ORM model

**Files:**
- Create: `backend/app/models/token_coefficient.py`

- [ ] **Step 1: Write the ORM model**

Write the following to `backend/app/models/token_coefficient.py`:

```python
"""Token coefficient (discount) config — global default + per-model override.

A single coefficient in (0, 1] is applied to input / cache_read / cache_creation /
output tokens. The coefficient is applied to the API response (SSE usage fields)
and to the PendingBilling write (so downstream RequestLog / BillingRecord /
UsageRecord all see the adjusted values).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TokenCoefficientConfig(Base):
    __tablename__ = "token_coefficient_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False)
    model_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=True
    )
    coefficient: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("model_id", name="uq_token_coefficient_configs_model_id"),
        CheckConstraint(
            "coefficient > 0 AND coefficient <= 1",
            name="ck_token_coefficient_configs_range",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND model_id IS NULL) OR "
            "(scope_type = 'model' AND model_id IS NOT NULL)",
            name="ck_token_coefficient_configs_scope_model",
        ),
    )
```

- [ ] **Step 2: Verify model imports and creates table**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run python -c "from app.models.token_coefficient import TokenCoefficientConfig; from app.database import Base; print(TokenCoefficientConfig.__tablename__); print(list(Base.metadata.tables.keys())[-1])"`
Expected: `token_coefficient_configs` printed twice (once from the class, once from metadata).

- [ ] **Step 3: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/models/token_coefficient.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(model): add TokenCoefficientConfig ORM"
```

---

## Task 3: Pure function `apply_coefficient` (TDD)

**Files:**
- Create: `backend/app/services/billing/token_coefficient.py`
- Create: `backend/tests/services/billing/test_apply_coefficient.py`

- [ ] **Step 1: Write the failing test**

Write the following to `backend/tests/services/billing/test_apply_coefficient.py`:

```python
"""Unit tests for the pure apply_coefficient() helper."""

import os
import sys

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _BACKEND)


def test_apply_coefficient_1_returns_same_values():
    """coefficient=1.0 is a fast path; values are returned unchanged."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=10,
        cache_read_tokens=20,
        cache_creation_tokens=30,
        output_tokens=40,
        coefficient=1.0,
    )
    assert out.input_tokens == 10
    assert out.cache_read_tokens == 20
    assert out.cache_creation_tokens == 30
    assert out.output_tokens == 40


def test_apply_coefficient_half_ceil_boundary():
    """7 * 0.5 = 3.5 -> ceil = 4.  8 * 0.5 = 4.0 -> ceil = 4."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=7,
        cache_read_tokens=8,
        cache_creation_tokens=1,
        output_tokens=0,
        coefficient=0.5,
    )
    assert out.input_tokens == 4
    assert out.cache_read_tokens == 4
    assert out.cache_creation_tokens == 1
    assert out.output_tokens == 0


def test_apply_coefficient_third_rounds_up():
    """1 * 0.33 = 0.33 -> ceil = 1."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=1,
        cache_read_tokens=2,
        cache_creation_tokens=3,
        output_tokens=4,
        coefficient=0.33,
    )
    assert out.input_tokens == 1
    assert out.cache_read_tokens == 1
    assert out.cache_creation_tokens == 1
    assert out.output_tokens == 2


def test_apply_coefficient_fields_are_independent():
    """Each field multiplies by the coefficient independently."""
    from app.services.billing.token_coefficient import apply_coefficient

    out = apply_coefficient(
        input_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=500,
        coefficient=0.5,
    )
    assert out.input_tokens == 500
    assert out.output_tokens == 250


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

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_apply_coefficient.py -v`
Expected: 5 failures, all with `ModuleNotFoundError: No module named 'app.services.billing.token_coefficient'`.

- [ ] **Step 3: Write minimal implementation**

Write the following to `backend/app/services/billing/token_coefficient.py`:

```python
"""Pure helpers for applying the admin-configured token coefficient (discount).

The coefficient is a float in (0, 1]; it is multiplied with each of the four
Anthropic token fields (input / cache_read / cache_creation / output). The
result is rounded up with math.ceil so a 0.5x coefficient never rounds below
half a token.

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
        cache_read_tokens=math.ceil(cache_read_tokens * coefficient),
        cache_creation_tokens=math.ceil(cache_creation_tokens * coefficient),
        output_tokens=math.ceil(output_tokens * coefficient),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_apply_coefficient.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/services/billing/token_coefficient.py backend/tests/services/billing/test_apply_coefficient.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(billing): add pure apply_coefficient helper with tests"
```

---

## Task 4: Pure function `_apply_coefficient_to_sse_event` (TDD)

**Files:**
- Create: `backend/app/services/streaming/__init__.py` (empty)
- Create: `backend/app/services/streaming/sse_rewrite.py`
- Create: `backend/tests/services/test_sse_rewrite.py`

- [ ] **Step 1: Write the failing test**

Write the following to `backend/tests/services/test_sse_rewrite.py`:

```python
"""Unit tests for the pure SSE rewrite helper."""

import os
import sys

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _BACKEND)


def _event(lines: list[str]) -> str:
    """Helper: join event lines with \n (no trailing newline)."""
    return "\n".join(lines)


def test_rewrite_message_start_adjusts_all_four_fields():
    """message_start with full usage — all four fields adjusted."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "event: message_start",
        'data: {"type":"message_start","message":{"id":"msg_1","usage":{'
        '"input_tokens":100,"cache_read_input_tokens":80,'
        '"cache_creation_input_tokens":20,"output_tokens":0}}}',
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # input: 100*0.5=50.0 -> 50; cache_read: 80*0.5=40.0 -> 40;
    # cache_creation: 20*0.5=10.0 -> 10; output: 0*0.5=0.0 -> 0
    assert '"input_tokens":50' in out
    assert '"cache_read_input_tokens":40' in out
    assert '"cache_creation_input_tokens":10' in out
    assert '"output_tokens":0' in out


def test_rewrite_message_delta_only_adjusts_output():
    """message_delta typically has only output_tokens; other fields absent → unchanged event."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "event: message_delta",
        'data: {"type":"message_delta","usage":{"output_tokens":7}}',
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # 7 * 0.5 = 3.5 -> ceil = 4
    assert '"output_tokens":4' in out


def test_rewrite_ping_event_unchanged():
    """ping event has no usage — passed through unchanged."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "event: ping",
        'data: {"type":"ping"}',
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert out == event


def test_rewrite_unparseable_data_line_unchanged():
    """If the data: line is not valid JSON, pass it through."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "event: error",
        "data: not-json",
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert out == event


def test_rewrite_usage_non_dict_unchanged():
    """If usage is not a dict (e.g. null), pass it through."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "event: message_start",
        'data: {"type":"message_start","message":{"id":"x","usage":null}}',
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert '"usage":null' in out


def test_rewrite_coefficient_1_short_circuits():
    """coefficient=1.0 returns the event byte-identically."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "event: message_start",
        'data: {"type":"message_start","message":{"id":"m","usage":{'
        '"input_tokens":100,"output_tokens":5}}}',
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 1.0)
    assert out == event


def test_rewrite_preserves_non_data_lines():
    """event: and id: lines are preserved verbatim."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event([
        "id: 42",
        "event: message_start",
        'data: {"type":"message_start","message":{"id":"x","usage":{"input_tokens":10}}}',
        "",
    ])
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert "id: 42" in out
    assert "event: message_start" in out
    # 10*0.5=5.0 -> 5
    assert '"input_tokens":5' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/test_sse_rewrite.py -v`
Expected: 7 failures, all with `ModuleNotFoundError: No module named 'app.services.streaming.sse_rewrite'`.

- [ ] **Step 3: Write minimal implementation**

Create the empty package marker: write to `backend/app/services/streaming/__init__.py`:

```python
"""Streaming helpers (SSE rewrite, etc.)."""
```

Write the following to `backend/app/services/streaming/sse_rewrite.py`:

```python
"""SSE event rewriting — apply the admin token coefficient to usage fields.

This is a pure function: it takes a single SSE event string and a coefficient,
and returns the event with the `usage` block in any `data:` line rewritten so
that each Anthropic token field is multiplied by the coefficient (ceil).

Behaviour:
- Non-data lines (`event:`, `id:`, comments) are passed through unchanged.
- A data: line whose payload is unparseable JSON is passed through unchanged.
- A data: line whose payload has no `usage` dict, or where `usage` is not a
  dict, is passed through unchanged.
- coefficient=1.0 short-circuits and returns the event byte-identically.
"""

import json
import math


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
    """Rewrite a single SSE event so that any data: line whose payload contains
    a 'usage' dict has its token counts multiplied by `coefficient` (ceil)."""
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/test_sse_rewrite.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/services/streaming backend/tests/services/test_sse_rewrite.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(streaming): add pure SSE rewrite helper with tests"
```

---

## Task 5: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/token_coefficient.py`

- [ ] **Step 1: Write the schemas**

Write the following to `backend/app/schemas/token_coefficient.py`:

```python
"""Pydantic schemas for the admin token coefficient endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class TokenCoefficientBase(BaseModel):
    coefficient: float = Field(..., gt=0, le=1)


class TokenCoefficientGlobalUpdate(TokenCoefficientBase):
    """Request body for PUT /api/admin/token-coefficients/global."""


class TokenCoefficientModelUpsert(TokenCoefficientBase):
    """Request body for PUT /api/admin/token-coefficients/models/{modelId}."""


class TokenCoefficientModelOut(BaseModel):
    model_id: int = Field(..., alias="modelId")
    model_name: str = Field(..., alias="modelName")
    model_public_name: str = Field(..., alias="modelPublicName")
    coefficient: float
    updated_at: datetime = Field(..., alias="updatedAt")
    updated_by_username: str | None = Field(None, alias="updatedByUsername")

    model_config = {"populate_by_name": True}


class TokenCoefficientGlobalOut(BaseModel):
    coefficient: float
    updated_at: datetime = Field(..., alias="updatedAt")
    updated_by_username: str | None = Field(None, alias="updatedByUsername")

    model_config = {"populate_by_name": True}


class TokenCoefficientsOverview(BaseModel):
    global_coefficient: float = Field(..., alias="globalCoefficient")
    global_meta: TokenCoefficientGlobalOut = Field(..., alias="globalMeta")
    overrides: list[TokenCoefficientModelOut]

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: Verify validation works**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run python -c "
from pydantic import ValidationError
from app.schemas.token_coefficient import TokenCoefficientGlobalUpdate
# valid
print(TokenCoefficientGlobalUpdate(coefficient=0.5).coefficient)
# invalid: 0
try:
    TokenCoefficientGlobalUpdate(coefficient=0)
except ValidationError as e:
    print('rejected 0:', e.errors()[0]['type'])
# invalid: > 1
try:
    TokenCoefficientGlobalUpdate(coefficient=1.5)
except ValidationError as e:
    print('rejected 1.5:', e.errors()[0]['type'])
# invalid: NaN
try:
    TokenCoefficientGlobalUpdate(coefficient=float('nan'))
except ValidationError as e:
    print('rejected nan:', e.errors()[0]['type'])
"`
Expected output:
```
0.5
rejected 0: greater_than
rejected 1.5: less_than_equal
rejected nan: ...
```

- [ ] **Step 3: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/schemas/token_coefficient.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(schema): add token coefficient Pydantic schemas"
```

---

## Task 6: `TokenCoefficientService` (resolution + in-memory cache, TDD)

**Files:**
- Create: `backend/app/services/token_coefficient_service.py`
- Create: `backend/tests/services/test_token_coefficient_service.py`

- [ ] **Step 1: Write the failing test**

Write the following to `backend/tests/services/test_token_coefficient_service.py`:

```python
"""Unit tests for TokenCoefficientService — resolution priority and cache invalidation."""

import os
import sys
from datetime import datetime, timezone

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _BACKEND)

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.model import Model
from app.models.token_coefficient import TokenCoefficientConfig


@pytest.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed: two models + one global row
    async with factory() as session:
        session.add_all([
            Model(id=1, public_name="m1", input_price=0, output_price=0, status="active"),
            Model(id=2, public_name="m2", input_price=0, output_price=0, status="active"),
        ])
        await session.flush()
        session.add(TokenCoefficientConfig(scope_type="global", coefficient=0.5))
        await session.commit()

    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_for_model_returns_global_when_no_override(db_factory):
    from app.services.token_coefficient_service import TokenCoefficientService

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 0.5
    assert svc.get_for_model(2) == 0.5


@pytest.mark.asyncio
async def test_model_override_wins_over_global(db_factory):
    from app.services.token_coefficient_service import TokenCoefficientService
    from app.models.token_coefficient import TokenCoefficientConfig

    async with db_factory() as session:
        session.add(
            TokenCoefficientConfig(scope_type="model", model_id=1, coefficient=0.2)
        )
        await session.commit()

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 0.2  # override
    assert svc.get_for_model(2) == 0.5  # falls back to global


@pytest.mark.asyncio
async def test_missing_global_falls_back_to_one(db_factory):
    """If the global row was deleted, the service returns 1.0."""
    from sqlalchemy import delete
    from app.services.token_coefficient_service import TokenCoefficientService
    from app.models.token_coefficient import TokenCoefficientConfig

    async with db_factory() as session:
        await session.execute(delete(TokenCoefficientConfig))
        await session.commit()

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 1.0


@pytest.mark.asyncio
async def test_invalidate_reloads_from_db(db_factory):
    from app.services.token_coefficient_service import TokenCoefficientService
    from app.models.token_coefficient import TokenCoefficientConfig

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 0.5

    # Update DB
    async with db_factory() as session:
        result = await session.execute(
            select(TokenCoefficientConfig).where(TokenCoefficientConfig.scope_type == "global")
        )
        row = result.scalar_one()
        row.coefficient = 0.8
        await session.commit()

    # Cache still stale
    assert svc.get_for_model(1) == 0.5

    # Invalidate reloads
    await svc.invalidate()
    assert svc.get_for_model(1) == 0.8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/test_token_coefficient_service.py -v`
Expected: 4 failures with `ModuleNotFoundError: No module named 'app.services.token_coefficient_service'`.

- [ ] **Step 3: Write minimal implementation**

Write the following to `backend/app/services/token_coefficient_service.py`:

```python
"""Token coefficient service — resolution + in-memory cache.

Loads `token_coefficient_configs` rows on startup (or on invalidate) into
two structures:
- `_global_coefficient: float` — the single global row's coefficient
- `_overrides: dict[int, float]` — model_id -> coefficient

`get_for_model(model_id)` is synchronous and O(1). It is safe to call from the
hot path inside the proxy. Admin write endpoints must call `invalidate()`
after a successful commit so the next request sees the new value.
"""

import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.token_coefficient import TokenCoefficientConfig

logger = logging.getLogger("cloude-gateway.token_coefficient")

GLOBAL_SCOPE = "global"
MODEL_SCOPE = "model"


class TokenCoefficientService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._global_coefficient: float = 1.0
        self._overrides: dict[int, float] = {}

    async def load(self) -> None:
        """Reload the cache from the DB. Safe to call multiple times."""
        async with self._session_factory() as session:
            result = await session.execute(select(TokenCoefficientConfig))
            rows = result.scalars().all()

        new_global: float | None = None
        new_overrides: dict[int, float] = {}
        for row in rows:
            if row.scope_type == GLOBAL_SCOPE:
                new_global = row.coefficient
            elif row.scope_type == MODEL_SCOPE and row.model_id is not None:
                new_overrides[row.model_id] = row.coefficient

        self._global_coefficient = 1.0 if new_global is None else new_global
        self._overrides = new_overrides

        if new_global is None:
            logger.warning(
                "TokenCoefficientService: no global row found; falling back to 1.0"
            )

    async def invalidate(self) -> None:
        """Reload after an admin write."""
        await self.load()

    def get_for_model(self, model_id: int) -> float:
        """Return the effective coefficient for a model.

        Priority: per-model override > global > 1.0 (defensive default).
        """
        return self._overrides.get(model_id, self._global_coefficient)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/test_token_coefficient_service.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/services/token_coefficient_service.py backend/tests/services/test_token_coefficient_service.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(service): add TokenCoefficientService with resolution and cache"
```

---

## Task 7: Admin CRUD router (TDD)

**Files:**
- Create: `backend/app/routers/admin_token_coefficients.py`
- Create: `backend/tests/test_admin_token_coefficients_router.py`

- [ ] **Step 1: Write the failing test**

Write the following to `backend/tests/test_admin_token_coefficients_router.py`:

```python
"""Integration tests for the admin /api/admin/token-coefficients endpoints."""

import os
import sys
from datetime import datetime, timezone

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.model import Model
from app.models.token_coefficient import TokenCoefficientConfig
from app.models.user import User
from app.services.token_coefficient_service import TokenCoefficientService
from server import app


@pytest.fixture(autouse=True)
async def setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    async with session_factory() as session:
        session.add_all([
            User(id=1, email="admin@example.com", password_hash="x",
                 balance=0, role="admin", status="active"),
            Model(id=1, public_name="m1", input_price=0, output_price=0, status="active"),
            Model(id=2, public_name="m2", input_price=0, output_price=0, status="active"),
            TokenCoefficientConfig(scope_type="global", coefficient=1.0),
        ])
        await session.commit()

    # Attach the service the router depends on
    app.state.token_coefficient_service = TokenCoefficientService(session_factory)
    await app.state.token_coefficient_service.load()

    # Auth override: pretend every request is admin id=1
    from app.dependencies import get_current_admin
    async def _admin_override():
        return User(id=1, email="admin@example.com", password_hash="x",
                    balance=0, role="admin", status="active")
    app.dependency_overrides[get_current_admin] = _admin_override

    yield

    app.dependency_overrides.clear()
    await engine.dispose()
    del app.state.token_coefficient_service


@pytest.mark.asyncio
async def test_get_overview_returns_global_and_empty_overrides():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/admin/token-coefficients")
    assert r.status_code == 200
    data = r.json()
    assert data["globalCoefficient"] == 1.0
    assert data["overrides"] == []


@pytest.mark.asyncio
async def test_put_global_validates_coefficient():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 0.5},
        )
        assert r.status_code == 200
        assert r.json()["coefficient"] == 0.5

        # invalid: 0
        r2 = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 0},
        )
        assert r2.status_code == 422

        # invalid: > 1
        r3 = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 1.5},
        )
        assert r3.status_code == 422


@pytest.mark.asyncio
async def test_put_global_invalidates_cache():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # before
        assert app.state.token_coefficient_service.get_for_model(1) == 1.0
        # write
        r = await ac.put(
            "/api/admin/token-coefficients/global",
            json={"coefficient": 0.7},
        )
        assert r.status_code == 200
        # cache should have been invalidated and reloaded
        assert app.state.token_coefficient_service.get_for_model(1) == 0.7


@pytest.mark.asyncio
async def test_upsert_model_creates_then_updates_override():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.3},
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["modelId"] == 1
        assert body1["coefficient"] == 0.3

        # second call updates
        r2 = await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.4},
        )
        assert r2.status_code == 200
        assert r2.json()["coefficient"] == 0.4

        # cache reflects update
        assert app.state.token_coefficient_service.get_for_model(1) == 0.4
        assert app.state.token_coefficient_service.get_for_model(2) == 1.0  # global


@pytest.mark.asyncio
async def test_upsert_model_404_for_unknown_model():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.put(
            "/api/admin/token-coefficients/models/999",
            json={"coefficient": 0.5},
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_model_override_removes_it():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.3},
        )
        assert app.state.token_coefficient_service.get_for_model(1) == 0.3

        r = await ac.delete("/api/admin/token-coefficients/models/1")
        assert r.status_code == 204

        # falls back to global (1.0)
        assert app.state.token_coefficient_service.get_for_model(1) == 1.0


@pytest.mark.asyncio
async def test_get_overview_lists_overrides():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.put(
            "/api/admin/token-coefficients/models/1",
            json={"coefficient": 0.3},
        )
        r = await ac.get("/api/admin/token-coefficients")
        assert r.status_code == 200
        data = r.json()
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["modelId"] == 1
        assert data["overrides"][0]["coefficient"] == 0.3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/test_admin_token_coefficients_router.py -v`
Expected: collection error / 404 on every endpoint (router not yet registered).

- [ ] **Step 3: Write the router**

Write the following to `backend/app/routers/admin_token_coefficients.py`:

```python
"""Admin /api/admin/token-coefficients router — manage the global default and
per-model overrides for the token coefficient (discount) feature.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.model import Model
from app.models.token_coefficient import TokenCoefficientConfig
from app.models.user import User
from app.schemas.token_coefficient import (
    TokenCoefficientGlobalOut,
    TokenCoefficientGlobalUpdate,
    TokenCoefficientModelOut,
    TokenCoefficientModelUpsert,
    TokenCoefficientsOverview,
)
from app.services.token_coefficient_service import (
    GLOBAL_SCOPE,
    MODEL_SCOPE,
    TokenCoefficientService,
)

logger = logging.getLogger("cloude-gateway.admin_token_coefficients")

router = APIRouter(prefix="/api/admin/token-coefficients", tags=["admin-token-coefficients"])


async def _username_for(db: AsyncSession, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    from app.models.user import User as UserModel
    user = await db.get(UserModel, user_id)
    return user.email if user else None


@router.get("", response_model=TokenCoefficientsOverview)
async def get_overview(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return the global coefficient and all per-model overrides."""
    result = await db.execute(select(TokenCoefficientConfig))
    rows = result.scalars().all()

    global_row = next((r for r in rows if r.scope_type == GLOBAL_SCOPE), None)
    override_rows = [r for r in rows if r.scope_type == MODEL_SCOPE and r.model_id is not None]

    global_meta = TokenCoefficientGlobalOut(
        coefficient=global_row.coefficient if global_row else 1.0,
        updatedAt=global_row.updated_at if global_row else datetime.now(timezone.utc),
        updatedByUsername=await _username_for(db, global_row.updated_by) if global_row else None,
    )

    overrides: list[TokenCoefficientModelOut] = []
    for r in override_rows:
        model = await db.get(Model, r.model_id)
        overrides.append(TokenCoefficientModelOut(
            modelId=r.model_id,
            modelName=model.name if model else f"#{r.model_id}",
            modelPublicName=model.public_name if model else "",
            coefficient=r.coefficient,
            updatedAt=r.updated_at,
            updatedByUsername=await _username_for(db, r.updated_by),
        ))

    return TokenCoefficientsOverview(
        globalCoefficient=global_meta.coefficient,
        globalMeta=global_meta,
        overrides=overrides,
    )


@router.put("/global", response_model=TokenCoefficientGlobalOut)
async def update_global(
    data: TokenCoefficientGlobalUpdate,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Set the global default coefficient."""
    result = await db.execute(
        select(TokenCoefficientConfig).where(TokenCoefficientConfig.scope_type == GLOBAL_SCOPE)
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = TokenCoefficientConfig(
            scope_type=GLOBAL_SCOPE, model_id=None,
            coefficient=data.coefficient, updated_by=admin.id, updated_at=now,
        )
        db.add(row)
    else:
        row.coefficient = data.coefficient
        row.updated_by = admin.id
        row.updated_at = now
    await db.commit()
    await request.app.state.token_coefficient_service.invalidate()
    return TokenCoefficientGlobalOut(
        coefficient=row.coefficient,
        updatedAt=row.updated_at,
        updatedByUsername=admin.email,
    )


@router.put("/models/{model_id}", response_model=TokenCoefficientModelOut)
async def upsert_model(
    model_id: int,
    data: TokenCoefficientModelUpsert,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a per-model override."""
    model = await db.get(Model, model_id)
    if model is None:
        raise AppException(
            status_code=404, error=f"模型 #{model_id} 不存在", code="MODEL_NOT_FOUND"
        )

    result = await db.execute(
        select(TokenCoefficientConfig).where(
            TokenCoefficientConfig.scope_type == MODEL_SCOPE,
            TokenCoefficientConfig.model_id == model_id,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = TokenCoefficientConfig(
            scope_type=MODEL_SCOPE, model_id=model_id,
            coefficient=data.coefficient, updated_by=admin.id, updated_at=now,
        )
        db.add(row)
    else:
        row.coefficient = data.coefficient
        row.updated_by = admin.id
        row.updated_at = now
    await db.commit()
    await request.app.state.token_coefficient_service.invalidate()
    return TokenCoefficientModelOut(
        modelId=model_id,
        modelName=model.name,
        modelPublicName=model.public_name,
        coefficient=row.coefficient,
        updatedAt=row.updated_at,
        updatedByUsername=admin.email,
    )


@router.delete("/models/{model_id}", status_code=204)
async def delete_model(
    model_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a per-model override (fall back to global)."""
    result = await db.execute(
        select(TokenCoefficientConfig).where(
            TokenCoefficientConfig.scope_type == MODEL_SCOPE,
            TokenCoefficientConfig.model_id == model_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        # idempotent: 204 even if no override existed
        return None
    await db.delete(row)
    await db.commit()
    await request.app.state.token_coefficient_service.invalidate()
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/test_admin_token_coefficients_router.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/routers/admin_token_coefficients.py backend/tests/test_admin_token_coefficients_router.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(router): add admin token coefficient endpoints"
```

---

## Task 8: Wire router into `app.py` and instantiate service in lifespan

**Files:**
- Modify: `backend/api/app.py` (lifespan + include_router)

- [ ] **Step 1: Add the import + router registration**

In `backend/api/app.py`, edit the imports/router block. The current block (lines 117–145) imports admin routers. Add the new one to that import group:

```python
    from app.routers import (
        admin_channels,
        admin_models,
        admin_providers,
        admin_redemption,
        admin_token_coefficients,
        admin_users,
        api_keys,
        auth,
        models,
        payment,
        providers,
        redemption,
        usage,
        v1_models,
    )
```

And add the include_router line in the same block:

```python
    app.include_router(admin_token_coefficients.router)
```

(Add it after `app.include_router(admin_users.router)`.)

- [ ] **Step 2: Instantiate the service in the lifespan**

In the same file, edit the `lifespan` function. The current lifespan (lines 29–82) does:
- `app.state.db_engine = engine` etc.
- `app.state.provider_registry = ProviderRegistry(settings=settings)`
- `app.state.billing_worker = BillingWorker(session_factory); await app.state.billing_worker.start()`

Add immediately **after** the `BillingWorker.start()` line (and **before** `logger.info("Application startup complete")`):

```python
        # Load token coefficient config (global + per-model overrides)
        from app.services.token_coefficient_service import TokenCoefficientService

        app.state.token_coefficient_service = TokenCoefficientService(session_factory)
        await app.state.token_coefficient_service.load()
        logger.info("TokenCoefficientService loaded")
```

- [ ] **Step 3: Add cleanup in shutdown**

In the shutdown section (after the `BillingWorker.stop()` block, before `await engine.dispose()`), add:

```python
        # TokenCoefficientService has no resources to release
```

(Or simply nothing — it's a no-op to leave it as-is. Skip this step; the service is stateless aside from the in-memory dict.)

- [ ] **Step 4: Verify the app boots**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && DATABASE_URL=sqlite+aiosqlite:///:memory: uv run python -c "
import asyncio
from server import app
async def boot():
    async with app.router.lifespan_context(app):
        svc = app.state.token_coefficient_service
        print('service loaded:', svc.get_for_model(999))
asyncio.run(boot())
"`
Expected: `service loaded: 1.0` (no overrides; falls back to global seed row, or 1.0 default if seed missing in in-memory DB).

- [ ] **Step 5: Verify the admin endpoint is registered**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run python -c "
from server import app
for route in app.routes:
    if 'token-coefficient' in getattr(route, 'path', ''):
        print(route.methods, route.path)
"`
Expected: lists GET `/api/admin/token-coefficients`, PUT `/api/admin/token-coefficients/global`, PUT `/api/admin/token-coefficients/models/{model_id}`, DELETE `/api/admin/token-coefficients/models/{model_id}`.

- [ ] **Step 6: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/api/app.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(app): register admin token-coefficients router and start service"
```

---

## Task 9: Apply coefficient in `proxy.py` (TDD via proxy integration test)

**Files:**
- Modify: `backend/app/routers/proxy.py`
- Create: `backend/tests/test_proxy_response_with_coefficient.py`

- [ ] **Step 1: Write the failing test**

Write the following to `backend/tests/test_proxy_response_with_coefficient.py`:

```python
"""End-to-end test: coefficient is applied to SSE response and to PendingBilling."""

import os
import sys
import uuid
from datetime import datetime, timezone

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider, ProviderKey
from app.models.token_coefficient import TokenCoefficientConfig
from app.models.user import User
from app.services.token_coefficient_service import TokenCoefficientService
from providers.registry import ProviderRegistry
from server import app


class _StubProvider:
    """Minimal provider that yields a single message_start and message_delta event."""

    name = "stub"

    async def stream_response(self, body, *, request_id=None, thinking_enabled=False):
        yield 'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_x","usage":{"input_tokens":100,"cache_read_input_tokens":80,"cache_creation_input_tokens":20,"output_tokens":0}}}\n\n'
        yield 'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":7}}\n\n'
        yield 'event: message_stop\ndata: {"type":"message_stop"}\n\n'


class _StubProviderRegistry:
    def __init__(self, provider):
        self._provider = provider

    def get(self, *_args, **_kwargs):
        return self._provider

    async def cleanup(self):
        pass


def _build_sse(chunks: list[str]) -> str:
    return "".join(chunks)


@pytest.fixture(autouse=True)
async def setup_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.db_engine = engine
    app.state.db_session_factory = session_factory

    # Seed minimal data for the proxy to resolve a model
    async with session_factory() as session:
        u = User(id=1, email="u@example.com", password_hash="x",
                 balance=10000, role="user", status="active")
        m = Model(id=1, public_name="m1", name="m1",
                  input_price=15000, output_price=75000, status="active")
        p = Provider(id=1, name="p1", channel_name="ch1",
                     api_base_url="https://x", auth_header="Authorization",
                     adapter="anthropic-messages", status="active", multiplier=1.0)
        route = ModelProviderRoute(model_id=1, provider_id=1, provider_model="m1", is_default=True)
        apikey = ApiKey(id=1, user_id=1, key_hash="hash", key_prefix="sk-aaaa",
                        channel_id=None, status="active")
        session.add_all([u, m, p, route, apikey])
        await session.commit()

    # Service: starts with global 0.5
    async with session_factory() as session:
        session.add(TokenCoefficientConfig(scope_type="global", coefficient=0.5))
        await session.commit()

    app.state.token_coefficient_service = TokenCoefficientService(session_factory)
    await app.state.token_coefficient_service.load()

    # Stub provider registry
    app.state.provider_registry = _StubProviderRegistry(_StubProvider())

    # Auth override: return the seeded user/key
    from api.dependencies import require_api_key
    from app.dependencies import get_current_user

    async def _override_require_api_key():
        # Re-read the seeded user+key in the active session
        async with session_factory() as session:
            u = await session.get(User, 1)
            k = await session.get(ApiKey, 1)
            return u, k

    app.dependency_overrides[require_api_key] = _override_require_api_key

    yield session_factory

    app.dependency_overrides.clear()
    await engine.dispose()
    del app.state.token_coefficient_service


@pytest.mark.asyncio
async def test_response_usage_is_adjusted(setup_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-aaaa-whatever"},
            json={
                "model": "m1",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200
    body = r.text

    # message_start usage: input 100*0.5=50, cache_read 80*0.5=40, cache_creation 20*0.5=10
    assert '"input_tokens":50' in body
    assert '"cache_read_input_tokens":40' in body
    assert '"cache_creation_input_tokens":10' in body
    # message_delta: output 7*0.5=3.5 -> ceil=4
    assert '"output_tokens":4' in body


@pytest.mark.asyncio
async def test_pending_billing_stores_adjusted_values(setup_db):
    session_factory = setup_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/messages",
            headers={"Authorization": "Bearer sk-aaaa-whatever"},
            json={
                "model": "m1",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 200

    # The billing_stream's finally block writes PendingBilling — read it back
    async with session_factory() as session:
        result = await session.execute(select(PendingBilling))
        pb = result.scalar_one_or_none()
        assert pb is not None, "expected a pending_billing row to be written"
        assert pb.input_tokens == 50
        assert pb.cache_read_tokens == 40
        assert pb.cache_creation_tokens == 10
        assert pb.output_tokens == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/test_proxy_response_with_coefficient.py -v`
Expected: tests fail (the chunks are not yet rewritten, `accumulated_usage` is not adjusted). Failures will be in the assertions on `'"input_tokens":50'` etc.

- [ ] **Step 3: Modify `proxy.py`**

Edit `backend/app/routers/proxy.py` in three places.

**Edit 1** — add the import at the top (after the existing imports from `app.services.billing.pending`):

```python
from app.services.billing.token_coefficient import apply_coefficient
from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event
```

**Edit 2** — inside `create_message` (after `model = await _lookup_model(db, body.model)` and before `_get_active_upstream_key`), add the coefficient lookup. Place it after the model lookup so we have `model.id`:

```python
    # ── 2a. Resolve token coefficient (discount) for this model ─
    coefficient = request.app.state.token_coefficient_service.get_for_model(model.id)
```

**Edit 3** — inside the `async for chunk in provider_instance.stream_response(...)` loop in `billing_stream` (after the model-remap block, right before the existing `yield chunk` / `yield chunk.replace(...)`), wrap the chunk in the SSE rewriter:

Before:
```python
                if _remap_model:
                    yield chunk.replace(_provider_model, _original_model)
                else:
                    yield chunk
```

After:
```python
                if _remap_model:
                    chunk = chunk.replace(_provider_model, _original_model)
                chunk = _apply_coefficient_to_sse_event(chunk, coefficient)
                yield chunk
```

**Edit 4** — inside the `finally` block of `billing_stream` (before `write_pending_billing`), apply the coefficient to `accumulated_usage`. Before:

```python
        finally:
            input_tokens = accumulated_usage["input_tokens"] or 0
            output_tokens = accumulated_usage["output_tokens"] or 0
            cache_read_tokens = accumulated_usage["cache_read_tokens"] or 0
            cache_creation_tokens = accumulated_usage["cache_creation_tokens"] or 0
            try:
                from app.services.billing.pending import write_pending_billing
                await write_pending_billing(
                    db,
                    request_id=uuid.uuid4(),
                    user_id=user_id,
                    api_key_id=api_key_id,
                    model_id=model.id,
                    route_id=routed.db_route_id,
                    provider_id=provider.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    upstream_message_id=upstream_message_id,
                )
```

After:
```python
        finally:
            adjusted = apply_coefficient(
                input_tokens=accumulated_usage["input_tokens"] or 0,
                cache_read_tokens=accumulated_usage["cache_read_tokens"] or 0,
                cache_creation_tokens=accumulated_usage["cache_creation_tokens"] or 0,
                output_tokens=accumulated_usage["output_tokens"] or 0,
                coefficient=coefficient,
            )
            try:
                from app.services.billing.pending import write_pending_billing
                await write_pending_billing(
                    db,
                    request_id=uuid.uuid4(),
                    user_id=user_id,
                    api_key_id=api_key_id,
                    model_id=model.id,
                    route_id=routed.db_route_id,
                    provider_id=provider.id,
                    input_tokens=adjusted.input_tokens,
                    output_tokens=adjusted.output_tokens,
                    cache_read_tokens=adjusted.cache_read_tokens,
                    cache_creation_tokens=adjusted.cache_creation_tokens,
                    upstream_message_id=upstream_message_id,
                )
```

(Remove the now-unused `input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_creation_tokens` locals at the top of the `finally` block; they were only used to feed `write_pending_billing`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/test_proxy_response_with_coefficient.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full backend test suite to confirm no regression**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest -x --ignore=tests/integration -q 2>&1 | tail -30`
Expected: all previously-passing tests still pass; only the new tests added. If any test breaks, inspect the diff and fix.

- [ ] **Step 6: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add backend/app/routers/proxy.py backend/tests/test_proxy_response_with_coefficient.py
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(proxy): apply token coefficient to SSE response and PendingBilling"
```

---

## Task 10: Alembic migration on the dev DB

**Files:** (no new files — running existing migration)

- [ ] **Step 1: Apply the migration to the dev PostgreSQL**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run alembic upgrade head`
Expected: "Running upgrade 015 -> 016, add token_coefficient_configs table (global + per-model override) and seed default global row".

- [ ] **Step 2: Verify the table and seed row exist**

Run: `cd /Users/wangdecheng/ai/claude-gateway/backend && uv run python -c "
import asyncio
from sqlalchemy import select, text
from app.database import create_async_engine_and_sessionmaker
from app.models.token_coefficient import TokenCoefficientConfig

async def main():
    engine, sf = create_async_engine_and_sessionmaker('postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api')
    async with sf() as s:
        rows = (await s.execute(select(TokenCoefficientConfig))).scalars().all()
        for r in rows:
            print(r.id, r.scope_type, r.model_id, r.coefficient)
    await engine.dispose()

asyncio.run(main())
"`
Expected: `1 global None 1.0`

- [ ] **Step 3: Commit (if any local migration state was generated)**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git status
# (No commit needed if alembic_version row was the only change — that lives in the DB)
```

---

## Task 11: Frontend API hooks

**Files:**
- Create: `frontend/lib/api/admin/token-coefficients.ts`

- [ ] **Step 1: Write the API module**

Write the following to `frontend/lib/api/admin/token-coefficients.ts`:

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

// --- Types ---

export interface TokenCoefficientModelItem {
  modelId: number;
  modelName: string;
  modelPublicName: string;
  coefficient: number;
  updatedAt: string;
  updatedByUsername: string | null;
}

export interface TokenCoefficientGlobalMeta {
  coefficient: number;
  updatedAt: string;
  updatedByUsername: string | null;
}

export interface TokenCoefficientsOverview {
  globalCoefficient: number;
  globalMeta: TokenCoefficientGlobalMeta;
  overrides: TokenCoefficientModelItem[];
}

// --- Hooks ---

export function useTokenCoefficients() {
  return useQuery<TokenCoefficientsOverview, ApiClientError>({
    queryKey: ["admin", "token-coefficients"],
    queryFn: () => apiClient<TokenCoefficientsOverview>("/admin/token-coefficients"),
  });
}

export function useUpdateGlobalCoefficient() {
  const qc = useQueryClient();
  return useMutation<TokenCoefficientGlobalMeta, ApiClientError, { coefficient: number }>({
    mutationFn: ({ coefficient }) =>
      apiClient<TokenCoefficientGlobalMeta>("/admin/token-coefficients/global", {
        method: "PUT",
        body: JSON.stringify({ coefficient }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "token-coefficients"] });
    },
  });
}

export function useUpsertModelCoefficient() {
  const qc = useQueryClient();
  return useMutation<
    TokenCoefficientModelItem,
    ApiClientError,
    { modelId: number; coefficient: number }
  >({
    mutationFn: ({ modelId, coefficient }) =>
      apiClient<TokenCoefficientModelItem>(
        `/admin/token-coefficients/models/${modelId}`,
        {
          method: "PUT",
          body: JSON.stringify({ coefficient }),
        }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "token-coefficients"] });
    },
  });
}

export function useDeleteModelCoefficient() {
  const qc = useQueryClient();
  return useMutation<void, ApiClientError, { modelId: number }>({
    mutationFn: ({ modelId }) =>
      apiClient<void>(`/admin/token-coefficients/models/${modelId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "token-coefficients"] });
    },
  });
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd /Users/wangdecheng/ai/claude-gateway/frontend && npx tsc --noEmit -p . 2>&1 | head -20`
Expected: no errors related to `token-coefficients.ts`. (If other pre-existing errors exist, ignore them.)

- [ ] **Step 3: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add frontend/lib/api/admin/token-coefficients.ts
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(frontend): add token coefficient API hooks"
```

---

## Task 12: Frontend admin page

**Files:**
- Create: `frontend/app/admin/discounts/page.tsx`
- Modify: `frontend/app/admin/layout.tsx` (add nav link + import)

- [ ] **Step 1: Write the admin page**

Write the following to `frontend/app/admin/discounts/page.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { Percent, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useTokenCoefficients,
  useUpdateGlobalCoefficient,
  useUpsertModelCoefficient,
  useDeleteModelCoefficient,
  type TokenCoefficientModelItem,
} from "@/lib/api/admin/token-coefficients";
import { useAdminModels, type AdminModelItem } from "@/lib/api/admin/models";
import { ApiClientError } from "@/lib/api/client";

function clampCoefficient(value: string): number | null {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0 || n > 1) return null;
  return n;
}

export default function DiscountsPage() {
  const overview = useTokenCoefficients();
  const models = useAdminModels();
  const updateGlobal = useUpdateGlobalCoefficient();
  const upsert = useUpsertModelCoefficient();
  const remove = useDeleteModelCoefficient();

  const [globalDraft, setGlobalDraft] = useState<string>("1");
  useEffect(() => {
    if (overview.data) setGlobalDraft(String(overview.data.globalCoefficient));
  }, [overview.data]);

  const overridesById = useMemo(() => {
    const map = new Map<number, TokenCoefficientModelItem>();
    (overview.data?.overrides ?? []).forEach((o) => map.set(o.modelId, o));
    return map;
  }, [overview.data]);

  const [editing, setEditing] = useState<{
    model: AdminModelItem;
    draft: string;
    error: string | null;
  } | null>(null);

  const handleSaveGlobal = async () => {
    const v = clampCoefficient(globalDraft);
    if (v === null) return;
    try {
      await updateGlobal.mutateAsync({ coefficient: v });
    } catch (e) {
      if (e instanceof ApiClientError) {
        alert(e.message);
      } else {
        throw e;
      }
    }
  };

  const handleSaveOverride = async () => {
    if (!editing) return;
    const v = clampCoefficient(editing.draft);
    if (v === null) {
      setEditing({ ...editing, error: "请输入 0–1 之间的小数" });
      return;
    }
    try {
      await upsert.mutateAsync({ modelId: editing.model.id, coefficient: v });
      setEditing(null);
    } catch (e) {
      if (e instanceof ApiClientError) {
        setEditing({ ...editing, error: e.message });
      } else {
        throw e;
      }
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-2">
        <Percent className="h-5 w-5" />
        <h1 className="text-xl font-semibold">折扣配置（Token 系数）</h1>
      </div>

      {/* Global */}
      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="text-sm font-medium text-slate-700">全局默认系数</h2>
        <p className="mt-1 text-xs text-slate-500">
          所有模型的默认折扣系数（0 &lt; x ≤ 1）。1.0 表示无折扣。
        </p>
        <div className="mt-4 flex items-end gap-3">
          <div className="w-40">
            <Label htmlFor="global-coefficient">系数</Label>
            <Input
              id="global-coefficient"
              type="number"
              step="0.01"
              min="0.01"
              max="1"
              value={globalDraft}
              onChange={(e) => setGlobalDraft(e.target.value)}
              disabled={overview.isLoading}
            />
          </div>
          <Button onClick={handleSaveGlobal} disabled={updateGlobal.isPending}>
            <Save className="mr-1 h-4 w-4" />
            保存
          </Button>
          {overview.data && (
            <span className="text-xs text-slate-500">
              最近更新：{new Date(overview.data.globalMeta.updatedAt).toLocaleString()}
              {overview.data.globalMeta.updatedByUsername
                ? ` by ${overview.data.globalMeta.updatedByUsername}`
                : ""}
            </span>
          )}
        </div>
      </section>

      {/* Per-model overrides */}
      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-6">
          <h2 className="text-sm font-medium text-slate-700">模型级覆盖</h2>
          <p className="mt-1 text-xs text-slate-500">
            为单个模型设置系数；未覆盖的模型使用全局值。
          </p>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>公开名称</TableHead>
              <TableHead>内部名称</TableHead>
              <TableHead>当前系数</TableHead>
              <TableHead>来源</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.data?.map((m) => {
              const ov = overridesById.get(m.id);
              return (
                <TableRow key={m.id}>
                  <TableCell className="font-medium">{m.publicName}</TableCell>
                  <TableCell className="text-slate-500">{m.description ?? "—"}</TableCell>
                  <TableCell>
                    {ov ? (
                      <Badge variant="info">{ov.coefficient.toFixed(2)}</Badge>
                    ) : (
                      <span className="text-slate-400">
                        {overview.data?.globalCoefficient.toFixed(2) ?? "—"} (全局)
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-slate-500">
                    {ov ? "覆盖" : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          setEditing({ model: m, draft: String(ov?.coefficient ?? overview.data?.globalCoefficient ?? 1), error: null })
                        }
                      >
                        {ov ? "修改" : "设置覆盖"}
                      </Button>
                      {ov && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => remove.mutate({ modelId: m.id })}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </section>

      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing && overridesById.has(editing.model.id) ? "修改" : "设置"}模型覆盖
            </DialogTitle>
            <DialogDescription>
              模型：{editing?.model.publicName}
            </DialogDescription>
          </DialogHeader>
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
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              取消
            </Button>
            <Button onClick={handleSaveOverride} disabled={upsert.isPending}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 2: Add the nav link**

Edit `frontend/app/admin/layout.tsx`:

a. Add `Percent` to the lucide-react import. The current import block is:

```tsx
import {
  Box,
  Server,
  Sliders,
  Users,
  Ticket,
  BarChart3,
  FileText,
  Search,
} from "lucide-react";
```

Change to:

```tsx
import {
  Box,
  Server,
  Sliders,
  Users,
  Ticket,
  BarChart3,
  FileText,
  Search,
  Percent,
} from "lucide-react";
```

b. Add a new item to the "配置中心" group. The current `items` array in that group is:

```tsx
items: [
  { href: "/admin/models", label: "模型管理", icon: Box },
  { href: "/admin/providers", label: "供应商管理", icon: Server },
  { href: "/admin/channels", label: "渠道配置", icon: Sliders },
],
```

Change to:

```tsx
items: [
  { href: "/admin/models", label: "模型管理", icon: Box },
  { href: "/admin/providers", label: "供应商管理", icon: Server },
  { href: "/admin/channels", label: "渠道配置", icon: Sliders },
  { href: "/admin/discounts", label: "折扣配置", icon: Percent },
],
```

- [ ] **Step 3: Verify the page renders**

Run: `cd /Users/wangdecheng/ai/claude-gateway/frontend && npm run lint 2>&1 | tail -20`
Expected: no errors. If there are errors related to the new file, fix them.

Run: `cd /Users/wangdecheng/ai/claude-gateway/frontend && npx tsc --noEmit -p . 2>&1 | grep -i "discounts\|token-coefficient" | head -20`
Expected: no output (or only pre-existing errors unrelated to this change).

- [ ] **Step 4: Commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add frontend/app/admin/discounts/page.tsx frontend/app/admin/layout.tsx
git -c user.email=wangdch@local -c user.name=wangdch commit -m "feat(frontend): add admin discounts page with global + per-model config"
```

---

## Task 13: Frontend tests

**Files:**
- Create: `frontend/tests/app/admin/discounts/page.test.tsx`

- [ ] **Step 1: Write the failing test**

Write the following to `frontend/tests/app/admin/discounts/page.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/api/admin/token-coefficients", () => ({
  useTokenCoefficients: vi.fn(),
  useUpdateGlobalCoefficient: vi.fn(),
  useUpsertModelCoefficient: vi.fn(),
  useDeleteModelCoefficient: vi.fn(),
}));
vi.mock("@/lib/api/admin/models", () => ({
  useAdminModels: vi.fn(),
}));

import * as tc from "@/lib/api/admin/token-coefficients";
import * as models from "@/lib/api/admin/models";
import DiscountsPage from "@/app/admin/discounts/page";

function renderWithQuery(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("DiscountsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (models.useAdminModels as any).mockReturnValue({
      data: [
        { id: 1, publicName: "model-a", description: null, inputPrice: 0, outputPrice: 0, status: "active", createdAt: "" },
        { id: 2, publicName: "model-b", description: null, inputPrice: 0, outputPrice: 0, status: "active", createdAt: "" },
      ],
      isLoading: false,
    });
    (tc.useUpdateGlobalCoefficient as any).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    (tc.useUpsertModelCoefficient as any).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
    });
    (tc.useDeleteModelCoefficient as any).mockReturnValue({
      mutate: vi.fn(),
    });
  });

  it("renders the global coefficient value and a model list", async () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 0.8,
        globalMeta: { coefficient: 0.8, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [],
      },
      isLoading: false,
    });
    renderWithQuery(<DiscountsPage />);
    expect(screen.getByDisplayValue("0.8")).toBeInTheDocument();
    expect(screen.getByText("model-a")).toBeInTheDocument();
    expect(screen.getByText("model-b")).toBeInTheDocument();
  });

  it("shows an existing override badge", () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 0.5,
        globalMeta: { coefficient: 0.5, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [
          { modelId: 1, modelName: "m1", modelPublicName: "model-a", coefficient: 0.3, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        ],
      },
      isLoading: false,
    });
    renderWithQuery(<DiscountsPage />);
    expect(screen.getByText("0.30")).toBeInTheDocument(); // Badge shows 0.30
    expect(screen.getByText("修改")).toBeInTheDocument(); // existing override
  });

  it("calls useUpdateGlobalCoefficient on save", async () => {
    (tc.useTokenCoefficients as any).mockReturnValue({
      data: {
        globalCoefficient: 1.0,
        globalMeta: { coefficient: 1.0, updatedAt: new Date().toISOString(), updatedByUsername: "admin" },
        overrides: [],
      },
      isLoading: false,
    });
    const mutate = vi.fn().mockResolvedValue({});
    (tc.useUpdateGlobalCoefficient as any).mockReturnValue({
      mutateAsync: mutate,
      isPending: false,
    });
    renderWithQuery(<DiscountsPage />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("系数");
    await user.clear(input);
    await user.type(input, "0.5");
    await user.click(screen.getByRole("button", { name: /保存/ }));
    await waitFor(() => {
      expect(mutate).toHaveBeenCalledWith({ coefficient: 0.5 });
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail (or skip if mocking issue)**

Run: `cd /Users/wangdecheng/ai/claude-gateway/frontend && npx vitest run tests/app/admin/discounts/page.test.tsx 2>&1 | tail -40`
Expected: tests fail (page doesn't exist yet) or pass after page is written. If they fail with import errors, fix the path.

- [ ] **Step 3: Commit (only if tests pass)**

If the tests pass, commit:

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add frontend/tests/app/admin/discounts/page.test.tsx
git -c user.email=wangdch@local -c user.name=wangdch commit -m "test(frontend): add discounts page tests"
```

If the tests have issues that take more than a small fix to resolve, note them and proceed to manual smoke testing — frontend tests are nice-to-have, not blocking.

---

## Task 14: Manual smoke test

- [ ] **Step 1: Start the backend**

In terminal 1:
```bash
cd /Users/wangdecheng/ai/claude-gateway/backend
uv run uvicorn server:app --host 0.0.0.0 --port 8082 --reload
```

- [ ] **Step 2: Start the frontend**

In terminal 2:
```bash
cd /Users/wangdecheng/ai/claude-gateway/frontend
npm run dev
```

- [ ] **Step 3: Set the global coefficient to 0.5**

Visit `http://localhost:3000/admin/discounts`, sign in as admin, set the global coefficient to `0.5`, click Save.

- [ ] **Step 4: Verify via the DB**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend
uv run python -c "
import asyncio
from sqlalchemy import select
from app.models.token_coefficient import TokenCoefficientConfig
from app.database import create_async_engine_and_sessionmaker

async def main():
    engine, sf = create_async_engine_and_sessionmaker('postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api')
    async with sf() as s:
        rows = (await s.execute(select(TokenCoefficientConfig))).scalars().all()
        for r in rows:
            print(r.id, r.scope_type, r.model_id, r.coefficient)
    await engine.dispose()
asyncio.run(main())
"
```
Expected: `1 global None 0.5`

- [ ] **Step 5: Call /v1/messages and verify response tokens are halved (ceil)**

```bash
curl -X POST http://localhost:8082/v1/messages \
  -H "Authorization: Bearer sk-YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "m1",
    "max_tokens": 100,
    "messages": [{"role":"user","content":"Hello"}]
  }' --no-buffer 2>&1 | grep -E 'input_tokens|output_tokens'
```
Expected: `input_tokens` is half the upstream (ceil); `output_tokens` likewise.

- [ ] **Step 6: Verify the persisted usage record reflects the discount**

After the request, query `usage_records` (use psql or the seed script) and confirm the `input_tokens` value is the adjusted one.

- [ ] **Step 7: Set a per-model override**

In the admin UI, click "设置覆盖" on `model-a`, enter `0.2`, save. Verify:
- The overview's `overrides` array contains `model-a` with `0.2`
- The cache (`app.state.token_coefficient_service.get_for_model(model_id)`) returns `0.2`

- [ ] **Step 8: Delete the override and confirm fallback**

In the admin UI, click the trash icon next to `model-a`'s override. Verify the row disappears and the table reverts to showing the global value.

---

## Task 15: Final cleanup and verification

- [ ] **Step 1: Run the full backend test suite**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend
uv run pytest -x --ignore=tests/integration -q 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 2: Run lint**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend
uv run ruff check .
cd /Users/wangdecheng/ai/claude-gateway/frontend
npm run lint
```
Expected: clean (or only pre-existing warnings).

- [ ] **Step 3: Update the spec's status to "approved"**

Edit `docs/superpowers/specs/2026-06-09-token-coefficient-design.md`, change the **Status** line from `draft` to `approved`. Add a `## Implementation Notes` section at the end recording the final commit hash and any deviations.

- [ ] **Step 4: Final commit**

```bash
cd /Users/wangdecheng/ai/claude-gateway
git add docs/superpowers/specs/2026-06-09-token-coefficient-design.md
git -c user.email=wangdch@local -c user.name=wangdch commit -m "docs(spec): mark token coefficient spec as approved"
```

---

## Self-Review

**Spec coverage check:**
| Spec section | Covered by task |
|--------------|-----------------|
| §1 Database table | Task 1 |
| §2 New files (ORM, schemas, router, service, helpers) | Tasks 2, 3, 4, 5, 6, 7 |
| §3 Modified files (app.py, proxy.py) | Tasks 8, 9 |
| §4 Coefficient resolution priority | Task 6 |
| §5 Pydantic schemas | Task 5 |
| §6 Admin API | Task 7 |
| §7 Pure functions | Tasks 3, 4 |
| §8 SSE rewrite in proxy.py | Task 9 |
| §4a One-write fix rationale | Task 9 (the `finally` block applies the coefficient exactly once) |
| §9 Frontend page | Tasks 11, 12 |
| Error handling table (coefficient=1.0, NaN, etc.) | Tasks 3, 4, 5, 6 cover all rows |
| Backend unit tests | Tasks 3, 4, 6, 7 |
| Backend integration tests | Task 9 |
| Frontend tests | Task 13 |
| Manual smoke | Task 14 |

**Placeholder scan:** No "TBD" / "TODO" / "implement later" / vague steps. Every step has either exact code, exact commands, or an exact decision.

**Type consistency:**
- `apply_coefficient` returns `AdjustedUsage` (4 ints) — used identically in Task 4 (test) and Task 9 (proxy finally).
- `_apply_coefficient_to_sse_event(event: str, coefficient: float) -> str` — used identically in Task 4 and Task 9.
- `TokenCoefficientService.get_for_model(model_id) -> float` — used in Tasks 6, 8, 9.
- `TokenCoefficientService.invalidate()` — called in admin router after every write (Task 7).
- Pydantic schema field names (`globalCoefficient`, `modelId`, etc.) — used consistently in router (Task 7) and frontend hooks (Task 11).
- Migration revision `016` with `down_revision = "015"` — matches the latest migration in `backend/alembic/versions/015_route_id_rename.py`.

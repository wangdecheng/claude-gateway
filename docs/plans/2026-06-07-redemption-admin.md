# Admin Redemption Code Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the admin redemption-code generation flow so `/admin/redemption` no longer 404s and admins can generate one-time balance redemption codes.

**Architecture:** Reuse the existing redemption table, hash helper, code format, and user redeem service. Add a narrow admin-only API for generating codes, then add a matching admin frontend page and API hook. Keep generated full codes visible only in the creation response.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Pydantic, bcrypt, Next.js App Router, React Query, Vitest, pytest.

### Task 1: Backend Schemas

**Files:**
- Modify: `backend/app/schemas/redemption.py`
- Test later through router tests in `backend/tests/test_admin_redemption.py`

**Step 1: Add admin request and response schemas**

Add these models below the existing redemption schemas:

```python
class AdminRedemptionCreateRequest(BaseModel):
    amount: int = Field(..., gt=0, description="兑换金额（分）")
    expires_in_days: int = Field(
        5,
        alias="expiresInDays",
        gt=0,
        description="有效天数",
    )

    model_config = {"populate_by_name": True}


class AdminRedemptionCreateResponse(BaseModel):
    id: int
    code: str
    code_prefix: str = Field(..., alias="codePrefix")
    amount: int
    status: str
    expires_at: str = Field(..., alias="expiresAt")
    created_at: str = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}
```

**Step 2: Run schema import smoke test**

Run:

```bash
cd backend && uv run python -c "from app.schemas.redemption import AdminRedemptionCreateRequest, AdminRedemptionCreateResponse; print('ok')"
```

Expected: prints `ok`.

**Step 3: Commit**

```bash
git add backend/app/schemas/redemption.py
git commit -m "feat(redemption): add admin code schemas"
```

### Task 2: Backend Router Tests

**Files:**
- Create: `backend/tests/test_admin_redemption.py`
- Reference: `backend/tests/test_admin_users.py`
- Reference: `backend/tests/integration/test_billing_flow.py`

**Step 1: Inspect existing test client pattern**

Open `backend/tests/test_admin_users.py` and copy its auth/session setup style. If it uses seeded users, reuse that instead of inventing new fixtures.

**Step 2: Write failing tests**

Create tests covering:

```python
async def test_admin_can_create_redemption_code(...):
    response = await client.post(
        "/api/admin/redemption",
        json={"amount": 1234},
        cookies=admin_cookie,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"].startswith("REDM-")
    assert data["codePrefix"] == data["code"][:9]
    assert data["amount"] == 1234
    assert data["status"] == "issued"
    assert data["expiresAt"]


async def test_admin_redemption_defaults_to_five_days(...):
    response = await client.post(
        "/api/admin/redemption",
        json={"amount": 100},
        cookies=admin_cookie,
    )
    assert response.status_code == 200
    expires_at = parse_iso(response.json()["expiresAt"])
    assert timedelta(days=4, hours=23) <= expires_at - now <= timedelta(days=5, minutes=1)


async def test_regular_user_cannot_create_redemption_code(...):
    response = await client.post(
        "/api/admin/redemption",
        json={"amount": 100},
        cookies=user_cookie,
    )
    assert response.status_code == 403


async def test_admin_redemption_rejects_invalid_amount(...):
    response = await client.post(
        "/api/admin/redemption",
        json={"amount": 0},
        cookies=admin_cookie,
    )
    assert response.status_code in {400, 422}


async def test_generated_redemption_code_can_be_redeemed(...):
    create_response = await client.post(
        "/api/admin/redemption",
        json={"amount": 500},
        cookies=admin_cookie,
    )
    code = create_response.json()["code"]

    redeem_response = await client.post(
        "/api/redeem",
        json={"code": code},
        cookies=user_cookie,
    )
    assert redeem_response.status_code == 200
    assert redeem_response.json()["amount"] == 500
```

Adjust fixture names to match the repo's existing tests.

**Step 3: Run tests to verify failure**

Run:

```bash
cd backend && uv run pytest tests/test_admin_redemption.py -q
```

Expected: fails because `/api/admin/redemption` is not registered or the schemas/router do not exist.

### Task 3: Backend Admin Router

**Files:**
- Create: `backend/app/routers/admin_redemption.py`
- Modify: `backend/api/app.py`
- Test: `backend/tests/test_admin_redemption.py`

**Step 1: Implement random code generation**

In `backend/app/routers/admin_redemption.py`, add:

```python
"""Admin redemption-code management router."""

import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from app.dependencies import get_current_admin
from app.exceptions import AppException
from app.models.redemption_code import RedemptionCode
from app.models.user import User
from app.schemas.redemption import (
    AdminRedemptionCreateRequest,
    AdminRedemptionCreateResponse,
)
from app.services.redemption_service import hash_code

router = APIRouter(prefix="/api/admin/redemption", tags=["admin-redemption"])

_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(4))
        for _ in range(3)
    ]
    return "REDM-" + "-".join(groups)
```

**Step 2: Implement create endpoint**

Add:

```python
async def _create_unique_code(db: AsyncSession) -> str:
    for _ in range(5):
        raw_code = _generate_code()
        existing = await db.execute(
            select(RedemptionCode.id).where(RedemptionCode.code_prefix == raw_code[:9])
        )
        if existing.scalar_one_or_none() is None:
            return raw_code
    raise AppException(
        status_code=500,
        error="兑换码生成失败，请重试",
        code="REDEMPTION_CODE_GENERATION_FAILED",
    )


@router.post("", response_model=AdminRedemptionCreateResponse)
async def create_redemption_code(
    body: AdminRedemptionCreateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    raw_code = await _create_unique_code(db)
    now = datetime.now(timezone.utc)
    item = RedemptionCode(
        code_hash=hash_code(raw_code),
        code_prefix=raw_code[:9],
        amount=body.amount,
        status="issued",
        expires_at=now + timedelta(days=body.expires_in_days),
        created_by=admin.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return AdminRedemptionCreateResponse(
        id=item.id,
        code=raw_code,
        codePrefix=item.code_prefix,
        amount=item.amount,
        status=item.status,
        expiresAt=item.expires_at.isoformat(),
        createdAt=item.created_at.isoformat(),
    )
```

**Step 3: Register router**

In `backend/api/app.py`, import `admin_redemption` with the other commerce routers and add:

```python
app.include_router(admin_redemption.router)
```

Place it near `admin_users.router`.

Do not modify `backend/app/main.py`; it is marked deprecated and the production app is created in `backend/api/app.py`.

**Step 4: Run backend tests**

Run:

```bash
cd backend && uv run pytest tests/test_admin_redemption.py -q
```

Expected: all new tests pass.

**Step 5: Run related regression tests**

Run:

```bash
cd backend && uv run pytest tests/test_admin_users.py tests/integration/test_billing_flow.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add backend/app/routers/admin_redemption.py backend/api/app.py backend/tests/test_admin_redemption.py
git commit -m "feat(redemption): add admin code generation api"
```

### Task 4: Frontend API Hook

**Files:**
- Create: `frontend/lib/api/admin/redemption.ts`
- Test later through page tests

**Step 1: Add API types and mutation**

Create:

```typescript
import { useMutation } from "@tanstack/react-query";
import { apiClient, ApiClientError } from "../client";

export interface AdminRedemptionCreateInput {
  amount: number;
  expiresInDays?: number;
}

export interface AdminRedemptionCreateResult {
  id: number;
  code: string;
  codePrefix: string;
  amount: number;
  status: string;
  expiresAt: string;
  createdAt: string;
}

export function useCreateAdminRedemptionCode() {
  return useMutation<
    AdminRedemptionCreateResult,
    ApiClientError,
    AdminRedemptionCreateInput
  >({
    mutationFn: (data) =>
      apiClient<AdminRedemptionCreateResult>("/admin/redemption", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}
```

**Step 2: Run frontend typecheck**

Run:

```bash
cd frontend && npm run typecheck
```

Expected: pass, or if the project has no `typecheck` script, use the repo's existing frontend validation script from `frontend/package.json`.

**Step 3: Commit**

```bash
git add frontend/lib/api/admin/redemption.ts
git commit -m "feat(redemption): add admin frontend api"
```

### Task 5: Frontend Admin Page

**Files:**
- Create: `frontend/app/admin/redemption/page.tsx`
- Reference: `frontend/app/admin/users/page.tsx`
- Reference: `frontend/components/ui/button.tsx`
- Reference: `frontend/components/ui/input.tsx`
- Reference: `frontend/lib/utils/format.ts`

**Step 1: Create page component**

Implement a client component with:

- `amountYuan` state as string.
- `expiresInDays` state defaulting to `"5"`.
- `result` state for the generated code.
- `error` state for API failures.
- Submit handler converts yuan to cents with `Math.round(Number(amountYuan) * 100)`.
- Reject empty, non-number, or non-positive amount client-side.
- Reject non-positive valid days client-side.

Use existing UI components where possible:

```tsx
"use client";

import { useState } from "react";
import { Copy, Ticket } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiClientError } from "@/lib/api/client";
import {
  useCreateAdminRedemptionCode,
  type AdminRedemptionCreateResult,
} from "@/lib/api/admin/redemption";
import { formatDate, formatPrice } from "@/lib/utils/format";
```

Render a form and success panel. For copy:

```typescript
await navigator.clipboard.writeText(result.code);
```

Fallback is not required unless tests show jsdom issues.

**Step 2: Keep generated code visible only after creation**

Do not add list or history. The page should show only the latest generated code in local state.

**Step 3: Run frontend validation**

Run:

```bash
cd frontend && npm run test -- --run
```

Expected: existing tests still pass.

**Step 4: Commit**

```bash
git add frontend/app/admin/redemption/page.tsx
git commit -m "feat(redemption): add admin generation page"
```

### Task 6: Frontend Tests

**Files:**
- Create: `frontend/tests/app/admin-redemption-page.test.tsx`
- Reference: `frontend/tests/app/keys-page.test.tsx`
- Reference: `frontend/tests/lib/AdminUsers.test.tsx`

**Step 1: Write page tests**

Cover:

```typescript
it("renders the redemption form with five-day default", () => {
  render(<AdminRedemptionPage />);
  expect(screen.getByRole("heading", { name: "兑换码管理" })).toBeInTheDocument();
  expect(screen.getByLabelText("有效天数")).toHaveValue(5);
});

it("shows the generated code after submit", async () => {
  mockApiClient.mockResolvedValueOnce({
    id: 1,
    code: "REDM-ABCD-EFGH-IJKL",
    codePrefix: "REDM-ABCD",
    amount: 500,
    status: "issued",
    expiresAt: "2026-06-12T00:00:00Z",
    createdAt: "2026-06-07T00:00:00Z",
  });
  render(<AdminRedemptionPage />);
  await user.type(screen.getByLabelText("金额"), "5");
  await user.click(screen.getByRole("button", { name: "生成兑换码" }));
  expect(await screen.findByText("REDM-ABCD-EFGH-IJKL")).toBeInTheDocument();
});
```

Adjust labels to match the final page text.

**Step 2: Run test to verify it passes**

Run:

```bash
cd frontend && npm run test -- --run frontend/tests/app/admin-redemption-page.test.tsx
```

Expected: pass.

**Step 3: Run frontend suite**

Run:

```bash
cd frontend && npm run test -- --run
```

Expected: pass.

**Step 4: Commit**

```bash
git add frontend/tests/app/admin-redemption-page.test.tsx
git commit -m "test(redemption): cover admin generation page"
```

### Task 7: End-to-End Verification

**Files:**
- No new files expected.

**Step 1: Run backend tests**

Run:

```bash
cd backend && uv run pytest tests/test_admin_redemption.py tests/test_admin_users.py -q
```

Expected: pass.

**Step 2: Run frontend tests**

Run:

```bash
cd frontend && npm run test -- --run
```

Expected: pass.

**Step 3: Run type checks or build**

Run the available frontend validation command from `frontend/package.json`.

Expected: pass.

**Step 4: Manual smoke test**

Start the app with the repo's normal dev command. Log in as admin, open `/admin/redemption`, generate a ¥1.00 code with the default 5-day validity, copy it, switch to a user account, redeem it at `/redeem`, and verify the balance increases by 100 cents.

**Step 5: Final commit if needed**

If Task 7 required small fixes, commit them:

```bash
git add <changed-files>
git commit -m "fix(redemption): complete admin redemption flow"
```

## Notes For Implementation

- Preserve unrelated dirty worktree changes. Only stage files touched by this feature.
- Do not store the full redemption code anywhere after generation.
- Do not add batch generation, listing, revoking, or exporting in this iteration.
- Keep the default validity at exactly 5 days unless the user changes it.
- Use integer cents on the API and database boundary; only the admin UI should accept yuan text.

# Admin 删除功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add delete functionality to admin model/provider/channel management with mixed hard/soft delete strategy and dependency blocking.

**Architecture:** Service-layer functions handle deletion logic (existence check → dependency check → hard/soft delete based on RequestLog references). Three new DELETE routes call these services. Frontend adds `useDelete*` hooks, delete buttons, and confirmation dialogs to each admin page.

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy async / Pytest with httpx ASGI transport / React 19 / TanStack Query / Tailwind CSS 4

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Create | `backend/app/schemas/delete.py` | `DeleteResponse` Pydantic schema |
| Modify | `backend/app/services/model_service.py` | Add `delete_model()` |
| Modify | `backend/app/services/provider_service.py` | Add `delete_provider()`, `delete_channel()` |
| Modify | `backend/app/routers/admin_models.py` | Add `DELETE /api/admin/models/{model_id}` |
| Modify | `backend/app/routers/admin_providers.py` | Add `DELETE /api/admin/providers/{provider_id}` |
| Modify | `backend/app/routers/admin_channels.py` | Add `DELETE /api/admin/channels/{channel_id}` |
| Modify | `backend/app/services/model_service.py` | Filter `status != "deleted"` in `list_all_models()` |
| Modify | `backend/app/services/provider_service.py` | Filter `status != "deleted"` in `list_providers()`, `list_channel_configs()` |
| Modify | `frontend/lib/api/admin/models.ts` | Add `useDeleteModel()` + `DeleteResult` type |
| Modify | `frontend/lib/api/admin/providers.ts` | Add `useDeleteProvider()` + `DeleteResult` type |
| Modify | `frontend/lib/api/admin/channels.ts` | Add `useDeleteChannel()` + `DeleteResult` type |
| Modify | `frontend/app/admin/models/page.tsx` | Add delete button + confirmation dialog |
| Modify | `frontend/app/admin/providers/page.tsx` | Add delete button + confirmation dialog |
| Modify | `frontend/app/admin/channels/page.tsx` | Add delete button + confirmation dialog |
| Create | `backend/tests/test_admin_delete.py` | Backend tests for all delete endpoints |

---

### Task 1: Create DeleteResponse Pydantic schema

**Files:**
- Create: `backend/app/schemas/delete.py`

- [ ] **Step 1: Write the schema file**

```python
"""Shared response schemas for delete operations."""

from pydantic import BaseModel, Field


class DeleteResponse(BaseModel):
    """Returned by DELETE endpoints for model/provider/channel."""

    deleted: bool = Field(..., description="Always true on success")
    method: str = Field(..., description="'hard' or 'soft'")
    id: int = Field(..., description="ID of the deleted entity")
```

- [ ] **Step 2: Verify the file parses without errors**

Run: `cd backend && uv run python -c "from app.schemas.delete import DeleteResponse; print(DeleteResponse(deleted=True, method='hard', id=1))"`
Expected: `deleted=True method='hard' id=1`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/delete.py
git commit -m "feat: add DeleteResponse schema for admin delete endpoints"
```

---

### Task 2: Add delete_model to model_service

**Files:**
- Modify: `backend/app/services/model_service.py`

- [ ] **Step 1: Add `delete_model` function**

Append to the end of `backend/app/services/model_service.py`:

```python
from app.models.request_log import RequestLog


async def delete_model(db: AsyncSession, model_id: int) -> dict:
    """Delete a model — hard if no RequestLog references, soft otherwise.

    Blocked if ChannelConfig records still reference this model.
    """
    # 1. Find model
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")
    if model.status == "deleted":
        raise AppException(status_code=404, error="模型不存在", code="MODEL_NOT_FOUND")

    # 2. Check blocking dependents: ChannelConfig
    ch_count_result = await db.execute(
        select(func.count(ChannelConfig.id)).where(ChannelConfig.model_id == model_id)
    )
    channel_count = ch_count_result.scalar_one()
    if channel_count > 0:
        raise AppException(
            status_code=409,
            error=f"无法删除：该模型下有 {channel_count} 个渠道配置，请先删除关联渠道",
            code="HAS_DEPENDENTS",
        )

    # 3. Check RequestLog references to decide hard vs soft
    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.model_id == model_id)
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        model.status = "deleted"
        method = "soft"
    else:
        await db.delete(model)
        method = "hard"

    await db.flush()
    logger.info("Model id=%d (%s) %s-deleted", model_id, model.public_name if has_request_logs else "", method)
    return {"deleted": True, "method": method, "id": model_id}
```

- [ ] **Step 2: Add `func` import at the top of the file if not already imported**

Check that `from sqlalchemy import func, select` exists at the top. If only `select` is imported, change to:

```python
from sqlalchemy import func, select
```

- [ ] **Step 3: Verify import**

Run: `cd backend && uv run python -c "from app.services.model_service import delete_model; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/model_service.py
git commit -m "feat: add delete_model service with mixed hard/soft delete"
```

---

### Task 3: Add delete_provider and delete_channel to provider_service

**Files:**
- Modify: `backend/app/services/provider_service.py`

- [ ] **Step 1: Add import for RequestLog and ChannelKey models**

At the top of `backend/app/services/provider_service.py`, ensure these imports exist alongside the existing model imports:

```python
from app.models.channel_key import ChannelKey
from app.models.request_log import RequestLog
```

If `ChannelKey` is not already imported, add it. The line `from app.models.model import ChannelConfig, Model` already exists.

- [ ] **Step 2: Add `delete_provider` function**

Append before the `# ── ChannelConfig management` section marker, or at the end of the file:

```python
async def delete_provider(db: AsyncSession, provider_id: int) -> dict:
    """Delete a provider — hard if no RequestLog references, soft otherwise.

    Blocked if Model, ChannelConfig, or active ProviderKey records reference this provider.
    """
    # 1. Find provider
    provider = await _get_provider_or_404(db, provider_id)
    if provider.status == "deleted":
        raise AppException(
            status_code=404, error="供应商不存在", code="PROVIDER_NOT_FOUND"
        )

    # 2. Check blocking dependents
    blocking: dict[str, int] = {}

    model_count_result = await db.execute(
        select(func.count(Model.id)).where(Model.provider_id == provider_id)
    )
    blocking["models"] = model_count_result.scalar_one()

    ch_count_result = await db.execute(
        select(func.count(ChannelConfig.id)).where(
            ChannelConfig.provider_id == provider_id
        )
    )
    blocking["channels"] = ch_count_result.scalar_one()

    key_count_result = await db.execute(
        select(func.count(ProviderKey.id)).where(
            ProviderKey.provider_id == provider_id,
            ProviderKey.status == "active",
        )
    )
    blocking["keys"] = key_count_result.scalar_one()

    total_blocking = blocking["models"] + blocking["channels"] + blocking["keys"]
    if total_blocking > 0:
        parts = []
        if blocking["models"]:
            parts.append(f"{blocking['models']} 个模型")
        if blocking["channels"]:
            parts.append(f"{blocking['channels']} 个渠道配置")
        if blocking["keys"]:
            parts.append(f"{blocking['keys']} 把活跃 Key")
        raise AppException(
            status_code=409,
            error=f"无法删除：供应商下有 {'、'.join(parts)}，请先清理",
            code="HAS_DEPENDENTS",
        )

    # 3. Check RequestLog to decide hard vs soft
    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(
            RequestLog.provider_id == provider_id
        )
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        provider.status = "deleted"
        method = "soft"
    else:
        # Hard delete: cascade-delete all ProviderKeys (revoked + active)
        pk_result = await db.execute(
            select(ProviderKey).where(ProviderKey.provider_id == provider_id)
        )
        for pk in pk_result.scalars().all():
            await db.delete(pk)
        await db.delete(provider)
        method = "hard"

    await db.flush()
    logger.info(
        "Provider id=%d (%s) %s-deleted",
        provider_id,
        provider.name if has_request_logs else "",
        method,
    )
    return {"deleted": True, "method": method, "id": provider_id}
```

- [ ] **Step 3: Add `delete_channel` function**

```python
async def delete_channel(db: AsyncSession, channel_id: int) -> dict:
    """Delete a channel config — hard if no RequestLog references, soft otherwise.

    Blocked if ChannelKey records reference this channel.
    """
    # 1. Find channel
    ch_result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise AppException(
            status_code=404, error="渠道配置不存在", code="CHANNEL_NOT_FOUND"
        )
    if channel.status == "deleted":
        raise AppException(
            status_code=404, error="渠道配置不存在", code="CHANNEL_NOT_FOUND"
        )

    # 2. Check blocking dependents: ChannelKey
    ck_count_result = await db.execute(
        select(func.count(ChannelKey.id)).where(
            ChannelKey.channel_id == channel_id
        )
    )
    ck_count = ck_count_result.scalar_one()
    if ck_count > 0:
        raise AppException(
            status_code=409,
            error=f"无法删除：该渠道下有 {ck_count} 个 Key 绑定，请先清理",
            code="HAS_DEPENDENTS",
        )

    # 3. Check RequestLog to decide hard vs soft
    rl_count_result = await db.execute(
        select(func.count(RequestLog.id)).where(
            RequestLog.channel_id == channel_id
        )
    )
    has_request_logs = rl_count_result.scalar_one() > 0

    if has_request_logs:
        channel.status = "deleted"
        if channel.is_default:
            channel.is_default = False
        method = "soft"
    else:
        await db.delete(channel)
        method = "hard"

    await db.flush()
    logger.info("Channel id=%d %s-deleted", channel_id, method)
    return {"deleted": True, "method": method, "id": channel_id}
```

- [ ] **Step 4: Verify imports**

Run: `cd backend && uv run python -c "from app.services.provider_service import delete_provider, delete_channel; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/provider_service.py
git commit -m "feat: add delete_provider and delete_channel service functions"
```

---

### Task 4: Add DELETE routes to admin routers

**Files:**
- Modify: `backend/app/routers/admin_models.py`
- Modify: `backend/app/routers/admin_providers.py`
- Modify: `backend/app/routers/admin_channels.py`

- [ ] **Step 1: Add DELETE endpoint to admin_models.py**

Insert import at the top of `backend/app/routers/admin_models.py`:

```python
from app.schemas.delete import DeleteResponse
```

Append at end of the file:

```python
@router.delete(
    "/{model_id}",
    response_model=DeleteResponse,
)
async def delete_model(
    model_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a model — hard if no request logs, soft otherwise."""
    result = await model_service.delete_model(db, model_id)
    await db.commit()
    return result
```

- [ ] **Step 2: Add DELETE endpoint to admin_providers.py**

Insert import at the top:

```python
from app.schemas.delete import DeleteResponse
```

Append before the `# ── Provider Key management` section, after the toggle endpoint:

```python
@router.delete("/{provider_id}", response_model=DeleteResponse)
async def delete_provider(
    provider_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a provider — hard if no request logs, soft otherwise."""
    result = await provider_service.delete_provider(db, provider_id)
    await db.commit()
    return result
```

- [ ] **Step 3: Add DELETE endpoint to admin_channels.py**

Insert import at the top:

```python
from app.schemas.delete import DeleteResponse
```

Append at end of the file:

```python
@router.delete("/{channel_id}", response_model=DeleteResponse)
async def delete_channel(
    channel_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a channel config — hard if no request logs, soft otherwise."""
    result = await provider_service.delete_channel(db, channel_id)
    await db.commit()
    return result
```

- [ ] **Step 4: Verify routes load**

Run: `cd backend && uv run python -c "from server import app; routes = [r.path for r in app.routes if hasattr(r, 'methods')]; print([r for r in routes if 'delete' in str(r).lower() or 'admin' in str(r).lower()])"`
Expected: Should see the new DELETE routes listed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/admin_models.py backend/app/routers/admin_providers.py backend/app/routers/admin_channels.py
git commit -m "feat: add DELETE admin routes for models, providers, channels"
```

---

### Task 5: Filter deleted items from admin list queries

**Files:**
- Modify: `backend/app/services/model_service.py`
- Modify: `backend/app/services/provider_service.py`

- [ ] **Step 1: Filter models in list_all_models**

In `backend/app/services/model_service.py`, find the `select(Model, Provider.name, Provider.status, default_mult)` in `list_all_models`. Add `.where(Model.status != "deleted")` after the join:

```python
    result = await db.execute(
        select(Model, Provider.name, Provider.status, default_mult)
        .join(Provider, Model.provider_id == Provider.id)
        .where(Model.status != "deleted")
        .order_by(Model.created_at.desc())
    )
```

Also add `.where(Model.status.in_(["active", "inactive"]))` to `list_active_models` for safety (deleted models already excluded by `status == "active"` but be explicit):

The `list_active_models` function already filters `Model.status == "active"`, so no change needed there.

- [ ] **Step 2: Filter providers in list_providers**

In `backend/app/services/provider_service.py`, find `list_providers` function. Add `.where(Provider.status != "deleted")` before `.outerjoin`:

```python
    result = await db.execute(
        select(
            Provider,
            func.count(ProviderKey.id).label("key_count"),
            func.count(ProviderKey.id)
            .filter(ProviderKey.status == "active")
            .label("active_key_count"),
        )
        .where(Provider.status != "deleted")
        .outerjoin(ProviderKey, ProviderKey.provider_id == Provider.id)
        .group_by(Provider.id)
        .order_by(Provider.created_at.desc())
    )
```

- [ ] **Step 3: Filter channels in list_channel_configs**

In `list_channel_configs`, add `.where(ChannelConfig.status != "deleted")`:

```python
    result = await db.execute(
        select(ChannelConfig, Model, Provider)
        .join(Model, ChannelConfig.model_id == Model.id)
        .join(Provider, ChannelConfig.provider_id == Provider.id)
        .where(ChannelConfig.status != "deleted")
        .order_by(Model.public_name.asc(), ChannelConfig.multiplier.asc())
    )
```

- [ ] **Step 4: Verify**

Run: `cd backend && uv run python -c "from app.services.model_service import list_all_models; from app.services.provider_service import list_providers, list_channel_configs; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/model_service.py backend/app/services/provider_service.py
git commit -m "feat: filter deleted items from admin list queries"
```

---

### Task 6: Add useDeleteModel frontend hook

**Files:**
- Modify: `frontend/lib/api/admin/models.ts`

- [ ] **Step 1: Add DeleteResult type and useDeleteModel hook**

Append at end of `frontend/lib/api/admin/models.ts`:

```typescript
// --- Delete ---

export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteModel() {
  const queryClient = useQueryClient();

  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/models/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "models"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit lib/api/admin/models.ts 2>&1 || true`
Expected: No errors related to the new code.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api/admin/models.ts
git commit -m "feat: add useDeleteModel frontend hook"
```

---

### Task 7: Add useDeleteProvider frontend hook

**Files:**
- Modify: `frontend/lib/api/admin/providers.ts`

- [ ] **Step 1: Add DeleteResult type and useDeleteProvider hook**

Append at end of `frontend/lib/api/admin/providers.ts`:

```typescript
// --- Delete ---

export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteProvider() {
  const queryClient = useQueryClient();

  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/providers/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "providers"] });
    },
  });
}
```

- [ ] **Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit lib/api/admin/providers.ts 2>&1 || true`
Expected: No relevant errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api/admin/providers.ts
git commit -m "feat: add useDeleteProvider frontend hook"
```

---

### Task 8: Add useDeleteChannel frontend hook

**Files:**
- Modify: `frontend/lib/api/admin/channels.ts`

- [ ] **Step 1: Add DeleteResult type and useDeleteChannel hook**

Append at end of `frontend/lib/api/admin/channels.ts`:

```typescript
// --- Delete ---

export interface DeleteResult {
  deleted: boolean;
  method: "hard" | "soft";
  id: number;
}

export function useDeleteChannel() {
  const queryClient = useQueryClient();

  return useMutation<DeleteResult, ApiClientError, number>({
    mutationFn: (id) =>
      apiClient<DeleteResult>(`/admin/channels/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}
```

- [ ] **Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit lib/api/admin/channels.ts 2>&1 || true`
Expected: No relevant errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api/admin/channels.ts
git commit -m "feat: add useDeleteChannel frontend hook"
```

---

### Task 9: Add delete UI to admin models page

**Files:**
- Modify: `frontend/app/admin/models/page.tsx`

- [ ] **Step 1: Add imports**

Change the lucide-react import line to include `Trash2`:

```typescript
import { Plus, Pencil, Power, PowerOff, Trash2 } from "lucide-react";
```

Add the import for `useDeleteModel` and `DeleteResult`:

```typescript
import {
  useAdminModels,
  useAdminProviders,
  useCreateModel,
  useUpdateModel,
  useToggleModelStatus,
  useDeleteModel,
  type AdminModelItem,
  type ModelCreateInput,
  type ModelUpdateInput,
} from "@/lib/api/admin/models";
```

- [ ] **Step 2: Add state and hook in component body**

After the existing `toggleMutation` line in the component:

```typescript
  const toggleMutation = useToggleModelStatus();
  const deleteMutation = useDeleteModel();
```

After the `toggleError` state:

```typescript
  const [toggleError, setToggleError] = useState<string | null>(null);

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<AdminModelItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
```

- [ ] **Step 3: Add delete handler**

After `handleToggleConfirm`:

```typescript
  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("删除失败，请重试");
      }
    }
  };
```

- [ ] **Step 4: Add delete button in table operation column**

In the TableCell operation column, after the toggle button, add the delete button:

```tsx
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(row.original)}
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setToggleTarget(row.original)}
                        >
                          {row.original.status === "active" ? (
                            <PowerOff className="h-4 w-4 text-orange-500" />
                          ) : (
                            <Power className="h-4 w-4 text-green-500" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setDeleteTarget(row.original);
                            setDeleteError(null);
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </TableCell>
```

- [ ] **Step 5: Add delete confirmation dialog**

Add after the toggle confirmation Dialog (before the closing `</div>` of the page):

```tsx
      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => { setDeleteTarget(null); setDeleteError(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除模型</DialogTitle>
            <DialogDescription>
              确定要删除 <strong>{deleteTarget?.publicName}</strong> 吗？
              <br />
              删除后将无法通过该模型发起 API 请求。
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {deleteError}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/admin/models/page.tsx
git commit -m "feat: add delete button and confirmation dialog to models admin page"
```

---

### Task 10: Add delete UI to admin providers page

**Files:**
- Modify: `frontend/app/admin/providers/page.tsx`

- [ ] **Step 1: Update imports in providers page**

`Trash2` is already imported. Add `useDeleteProvider` import:

```typescript
import {
  useAdminProviders,
  useCreateProvider,
  useUpdateProvider,
  useToggleProviderStatus,
  useProviderKeys,
  useAddProviderKeys,
  useRevokeProviderKey,
  useDeleteProvider,
  type AdminProviderItem,
  type ProviderCreateInput,
  type ProviderUpdateInput,
  type ProviderKeyItem,
} from "@/lib/api/admin/providers";
```

- [ ] **Step 2: Add state and hook in AdminProvidersPage**

After the toggleMutation line:

```typescript
  const toggleMutation = useToggleProviderStatus();
  const deleteMutation = useDeleteProvider();

  // Delete confirmation state
  const [deleteTarget, setDeleteTarget] = useState<AdminProviderItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
```

- [ ] **Step 3: Add delete handler**

After `handleToggle`:

```typescript
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("删除失败，请重试");
      }
    }
  };
```

- [ ] **Step 4: Pass delete handler to ProviderRow**

Update the ProviderRow call to accept delete props. The ProviderRow already receives callbacks — add `onDelete`:

```tsx
              {providers?.map((p) => (
                <ProviderRow
                  key={p.id}
                  provider={p}
                  isExpanded={expandedId === p.id}
                  onToggleExpand={() =>
                    setExpandedId(expandedId === p.id ? null : p.id)
                  }
                  onEdit={() => openEdit(p)}
                  onToggle={() => handleToggle(p.id)}
                  onDelete={() => { setDeleteTarget(p); setDeleteError(null); }}
                  isToggling={toggleMutation.isPending}
                />
              ))}
```

- [ ] **Step 5: Update ProviderRow signature and add delete button**

Update the ProviderRow function signature props:

```tsx
function ProviderRow({
  provider,
  isExpanded,
  onToggleExpand,
  onEdit,
  onToggle,
  onDelete,
  isToggling,
}: {
  provider: AdminProviderItem;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  isToggling: boolean;
}) {
```

In the operation cell (the last `<td>`), add the delete button after the toggle button:

```tsx
        <td className="px-4 py-3 text-right">
          <div className="flex items-center justify-end gap-1">
            <Button variant="ghost" size="sm" onClick={onEdit}>
              编辑
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggle}
              disabled={isToggling}
            >
              {provider.status === "active" ? "停用" : "启用"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              className="text-red-500 hover:text-red-600"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </td>
```

- [ ] **Step 6: Add delete confirmation dialog**

After the existing ProviderEditForm Dialog, before the closing `</div>`:

```tsx
      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => { setDeleteTarget(null); setDeleteError(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除供应商</DialogTitle>
            <DialogDescription>
              确定要删除 <strong>{deleteTarget?.name}</strong> 吗？
              <br />
              删除后将无法通过该供应商转发 API 请求。
            </DialogDescription>
          </DialogHeader>
          {deleteError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {deleteError}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/admin/providers/page.tsx
git commit -m "feat: add delete button and confirmation dialog to providers admin page"
```

---

### Task 11: Add delete UI to admin channels page

**Files:**
- Modify: `frontend/app/admin/channels/page.tsx`

- [ ] **Step 1: Add import**

Add `Trash2` to the lucide-react import:

```typescript
import { Plus, Trash2 } from "lucide-react";
```

Add `useDeleteChannel` import:

```typescript
import {
  useAdminChannels,
  useCreateChannel,
  useUpdateChannel,
  useToggleChannelStatus,
  useDeleteChannel,
  type AdminChannelItem,
} from "@/lib/api/admin/channels";
```

- [ ] **Step 2: Add state and hook**

After `toggleMutation`:

```typescript
  const toggleMutation = useToggleChannelStatus();
  const deleteMutation = useDeleteChannel();

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<AdminChannelItem | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
```

- [ ] **Step 3: Add delete handler**

After `handleToggle`:

```typescript
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setDeleteError(err.message);
      } else {
        setDeleteError("删除失败，请重试");
      }
    }
  };
```

- [ ] **Step 4: Add delete button in operation column**

In the table row operations, add a delete button after the toggle button:

```tsx
                <td className="px-4 py-3 text-right">
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(channel)}>
                      编辑
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setToggleConfirm(channel)}
                      disabled={toggleMutation.isPending}
                    >
                      {channel.status === "active" ? "停用" : "启用"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => { setDeleteTarget(channel); setDeleteError(null); }}
                      className="text-red-500 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </td>
```

- [ ] **Step 5: Add delete confirmation dialog**

Add after the toggle confirmation Dialog (before the closing `</div>` of the return):

```tsx
      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => { setDeleteTarget(null); setDeleteError(null); }}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>删除渠道</DialogTitle>
            <DialogDescription>
              确定要删除此渠道配置吗？
              <br />
              删除后该供应商-模型组合将不再可用。
            </DialogDescription>
          </DialogHeader>
          {deleteTarget && (
            <div className="rounded-md bg-slate-100 p-3 text-sm">
              <span className="font-mono">{deleteTarget.modelName}</span> → {deleteTarget.providerName}
            </div>
          )}
          {deleteError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-600">
              {deleteError}
            </div>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "删除中..." : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/admin/channels/page.tsx
git commit -m "feat: add delete button and confirmation dialog to channels admin page"
```

---

### Task 12: Backend tests for delete endpoints

**Files:**
- Create: `backend/tests/test_admin_delete.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for admin delete endpoints (model, provider, channel).

Uses FastAPI dependency_overrides to bypass auth so tests focus on
delete logic without requiring full cookie/JWT auth flows.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
from httpx import ASGITransport, AsyncClient

from server import app
from app.models.user import User


# ── Auth bypass fixture ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def override_admin_auth():
    """Replace get_current_admin with a no-op that returns a mock admin user.

    FastAPI dependency_overrides are scoped to the app, so we save/restore.
    """
    from app.dependencies import get_current_admin

    async def _mock_admin():
        return User(
            id=1,
            username="test_admin",
            email="test_admin@local",
            password_hash="unused",
            role="admin",
            status="active",
        )

    original = app.dependency_overrides.get(get_current_admin)
    app.dependency_overrides[get_current_admin] = _mock_admin
    yield
    if original is None:
        app.dependency_overrides.pop(get_current_admin, None)
    else:
        app.dependency_overrides[get_current_admin] = original


# ── Helper ──────────────────────────────────────────────────────────────


async def _setup_test_data(client: AsyncClient) -> dict:
    """Create a provider, model, and channel for delete testing.

    Returns dict with {provider_id, model_id, channel_id}.
    """
    # Create provider
    resp = await client.post(
        "/api/admin/providers",
        json={
            "name": "Test Provider Delete",
            "apiBaseUrl": "https://test.example.com/v1",
            "adapter": "openai-chat-completions",
            "keys": ["sk-test-key-12345678"],
        },
    )
    assert resp.status_code == 201, f"Provider create failed: {resp.text}"
    provider_id = resp.json()["id"]

    # Create model
    resp = await client.post(
        "/api/admin/models",
        json={
            "publicName": "Test Model Delete",
            "providerId": provider_id,
            "providerModelId": "test-model-delete",
            "inputPrice": 10000,
            "outputPrice": 20000,
            "multiplier": 1.0,
        },
    )
    assert resp.status_code == 201, f"Model create failed: {resp.text}"
    model_id = resp.json()["id"]

    # Create channel
    resp = await client.post(
        "/api/admin/channels",
        json={
            "modelId": model_id,
            "providerId": provider_id,
            "multiplier": 1.5,
        },
    )
    assert resp.status_code == 201, f"Channel create failed: {resp.text}"
    channel_id = resp.json()["id"]

    return {"provider_id": provider_id, "model_id": model_id, "channel_id": channel_id}


# ── Model Delete Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_model_success_hard():
    """Delete a model with no RequestLog references → hard delete.

    Must delete channel first (otherwise blocked by dependents).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        # Delete channel first to unblock model
        await client.delete(f"/api/admin/channels/{data['channel_id']}")

        resp = await client.delete(f"/api/admin/models/{data['model_id']}")
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        body = resp.json()
        assert body["deleted"] is True
        assert body["method"] == "hard"
        assert body["id"] == data["model_id"]

        # Verify it's gone from admin list
        list_resp = await client.get("/api/admin/models")
        ids = [m["id"] for m in list_resp.json()]
        assert data["model_id"] not in ids


@pytest.mark.asyncio
async def test_delete_model_not_found():
    """Deleting a non-existent model returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/admin/models/99999")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_model_blocked_by_channels():
    """Cannot delete a model that still has channel configs."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        resp = await client.delete(f"/api/admin/models/{data['model_id']}")
        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == "HAS_DEPENDENTS"


# ── Provider Delete Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_provider_blocked_by_models():
    """Cannot delete a provider that still has models."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        resp = await client.delete(f"/api/admin/providers/{data['provider_id']}")
        assert resp.status_code == 409
        assert resp.json()["code"] == "HAS_DEPENDENTS"


@pytest.mark.asyncio
async def test_delete_provider_success_after_cleanup():
    """Can delete a provider after models, channels, and keys are removed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        # Delete channel first
        await client.delete(f"/api/admin/channels/{data['channel_id']}")
        # Delete model
        await client.delete(f"/api/admin/models/{data['model_id']}")

        # Revoke the active key
        keys_resp = await client.get(
            f"/api/admin/providers/{data['provider_id']}/keys"
        )
        for key in keys_resp.json():
            if key["status"] == "active":
                await client.delete(
                    f"/api/admin/providers/{data['provider_id']}/keys/{key['id']}"
                )

        # Now delete provider
        resp = await client.delete(
            f"/api/admin/providers/{data['provider_id']}"
        )
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        assert resp.json()["deleted"] is True


@pytest.mark.asyncio
async def test_delete_provider_not_found():
    """Deleting a non-existent provider returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/admin/providers/99999")
        assert resp.status_code == 404


# ── Channel Delete Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_channel_success_hard():
    """Delete a channel with no RequestLog references → hard delete."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _setup_test_data(client)

        resp = await client.delete(f"/api/admin/channels/{data['channel_id']}")
        assert resp.status_code == 200, f"Delete failed: {resp.text}"
        body = resp.json()
        assert body["deleted"] is True
        assert body["method"] == "hard"

        # Verify it's gone from list
        list_resp = await client.get("/api/admin/channels")
        ids = [c["id"] for c in list_resp.json()]
        assert data["channel_id"] not in ids


@pytest.mark.asyncio
async def test_delete_channel_not_found():
    """Deleting a non-existent channel returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete("/api/admin/channels/99999")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests**

Run: `cd backend && uv run pytest tests/test_admin_delete.py -v`
Expected: All 7 tests pass. If any fail, fix the implementation or test before proceeding.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_admin_delete.py
git commit -m "test: add admin delete endpoint tests"
```

---

### Task 13: Integration verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && uv run pytest -v
```
Expected: All tests pass.

- [ ] **Step 2: Run frontend type check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No TypeScript errors.

- [ ] **Step 3: Manual verification checklist**

If running the dev server:
- [ ] Navigate to `/admin/models` — each row has a red trash icon
- [ ] Click trash → confirmation dialog appears
- [ ] Confirm → model deleted, list refreshed
- [ ] Navigate to `/admin/providers` — each row has a red trash icon
- [ ] Confirm delete → blocked if models exist, success otherwise
- [ ] Navigate to `/admin/channels` — each row has a red trash icon
- [ ] Confirm delete → success

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "chore: integration verification complete for admin delete feature"
```

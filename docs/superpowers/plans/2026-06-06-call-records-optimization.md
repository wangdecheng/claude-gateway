# 调用记录优化 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化调用记录页面：时间增加 hh:mm:ss，Token 拆分为输入/缓存读/缓存创建/输出四列，移除 total_tokens。

**Architecture:** 后端 UsageRecord 模型重命名字段、新增 cache 字段；proxy 结算时解析 message_delta 从 SSE 事件提取 usage 填充 accumulated_usage；前端 formatDate 全局加时分秒、表格列改为四个 token 字段。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy async / Next.js 15 / React 19 / TanStack Query / Tailwind CSS 4

---

### Task 1: 更新 UsageRecord 模型

**Files:**
- Modify: `backend/app/models/usage.py`

- [ ] **Step 1: 修改模型字段**

将 `request_tokens` 改为 `input_tokens`，`response_tokens` 改为 `output_tokens`，删除 `total_tokens`，新增 `cache_read_tokens` 和 `cache_creation_tokens`。

编辑 `backend/app/models/usage.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 单位: 分
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/models/usage.py
git commit -m "refactor(model): rename token columns, remove total_tokens, add cache fields"
```

---

### Task 2: 更新 usage_service

**Files:**
- Modify: `backend/app/services/usage_service.py`

- [ ] **Step 1: 更新 `record_usage` 函数签名和实现**

当前第 11-36 行，修改为：

```python
async def record_usage(
    db: AsyncSession,
    user_id: int,
    api_key_id: int,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_cents: int = 0,
) -> UsageRecord:
    """Record an API call usage entry.

    Flushes to the session but does NOT commit — the caller owns the
    transaction boundary so that usage + RequestLog (Epic 3) are atomic.
    """
    record = UsageRecord(
        user_id=user_id,
        api_key_id=api_key_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cost_cents=cost_cents,
    )
    db.add(record)
    await db.flush()
    return record
```

- [ ] **Step 2: 更新 `get_user_usage_stats` 中的 token 聚合**

找到第 52-56 行附近，将 `UsageRecord.total_tokens` 替换为四字段求和：

```python
# Today's stats
today_result = await db.execute(
    select(
        func.count(UsageRecord.id).label("calls"),
        func.coalesce(
            func.sum(
                UsageRecord.input_tokens
                + UsageRecord.cache_read_tokens
                + UsageRecord.cache_creation_tokens
                + UsageRecord.output_tokens
            ), 0
        ).label("tokens"),
        func.coalesce(func.sum(UsageRecord.cost_cents), 0).label("cost"),
    ).where(
        UsageRecord.user_id == user.id,
        UsageRecord.created_at >= today_start,
    )
)
```

每日统计部分也做同样替换（第 66-77 行附近的 `daily_result` 查询中）。

- [ ] **Step 3: 提交**

```bash
git add backend/app/services/usage_service.py
git commit -m "refactor(service): update record_usage and stats aggregation for cache fields"
```

---

### Task 3: 更新 proxy 结算流程

**Files:**
- Modify: `backend/app/routers/proxy.py`

- [ ] **Step 1: 新增 SSE usage 解析辅助函数**

在 proxy.py 顶部（`_settle_billing` 之前）添加 `import json`（如果尚未导入）和辅助函数：

```python
import json


def _extract_usage_from_sse_line(line: str) -> dict[str, int] | None:
    """Parse usage from a message_delta data line in the SSE stream.

    The provider splits SSE events into individual lines; this function
    matches a ``data: {..., "type": "message_delta", ...}`` line and
    extracts usage fields.
    """
    if not line.startswith("data:"):
        return None
    try:
        payload = json.loads(line.removeprefix("data:").strip())
    except json.JSONDecodeError:
        return None
    if payload.get("type") != "message_delta":
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
    }
```

- [ ] **Step 2: 更新 `accumulated_usage` 初始化**

在第 233 行，添加 `cache_creation_tokens`：

```python
accumulated_usage = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_creation_tokens": 0,
}
```

- [ ] **Step 3: 在 billing_stream 循环中解析 usage**

在 `billing_stream` 函数内（约第 256-263 行），对每个 chunk 调用解析：

```python
async def billing_stream():
    nonlocal accumulated_usage
    try:
        trace_event(
            stage="egress",
            event="proxy.stream.start",
            source="api",
            provider_id=routed.provider_id,
            gateway_model=body.model,
            provider_model=routed.provider_model,
        )
        async for chunk in provider_instance.stream_response(
            provider_body,
            request_id=f"req_{body.model}",
        ):
            # Parse usage from message_delta data lines
            usage = _extract_usage_from_sse_line(chunk)
            if usage:
                accumulated_usage["input_tokens"] = usage["input_tokens"]
                accumulated_usage["output_tokens"] = usage["output_tokens"]
                accumulated_usage["cache_read_tokens"] = usage["cache_read_input_tokens"]
                accumulated_usage["cache_creation_tokens"] = usage["cache_creation_input_tokens"]
            if _remap_model:
                yield chunk.replace(_provider_model, _original_model)
            else:
                yield chunk
    finally:
        # Extract usage from accumulated SSE events
        input_tokens = accumulated_usage["input_tokens"] or 100
        output_tokens = accumulated_usage["output_tokens"] or 0
        cache_read_tokens = accumulated_usage["cache_read_tokens"] or 0
        cache_creation_tokens = accumulated_usage["cache_creation_tokens"] or 0
        ...
```

- [ ] **Step 4: 更新 `_settle_billing` 传递 cache_creation_tokens**

给 `_settle_billing` 添加 `cache_creation_tokens` 参数，并传给 `record_usage`。修改调用处（约第 270-283 行）：

```python
settlement_task = asyncio.create_task(
    _settle_billing(
        session_factory=session_factory,
        user_id=user_id,
        api_key_id=api_key_id,
        model_name=body.model,
        reserve_amount=reserve_amount,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        input_price_micro_yuan=input_price,
        output_price_micro_yuan=output_price,
        cache_read_price_micro_yuan=cache_read_price,
    )
)
```

- [ ] **Step 5: 更新 `_settle_billing` 函数签名和 `record_usage` 调用**

修改 `_settle_billing` 函数签名（第 33-46 行）添加 `cache_creation_tokens` 参数，修改 `record_usage` 调用（第 70-78 行）：

```python
async def _settle_billing(
    *,
    session_factory,
    user_id: int,
    api_key_id: int,
    model_name: str,
    reserve_amount: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    input_price_micro_yuan: int,
    output_price_micro_yuan: int,
    cache_read_price_micro_yuan: int,
) -> None:
    ...
            await record_usage(
                db=settlement_db,
                user_id=user_id,
                api_key_id=api_key_id,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cost_cents=actual_cost,
            )
    ...
```

- [ ] **Step 6: 运行后端检查**

```bash
cd backend && uv run ruff check .
```
Expected: no errors (最多 unused import 警告，清理掉就行)

- [ ] **Step 7: 提交**

```bash
git add backend/app/routers/proxy.py
git commit -m "feat(proxy): parse message_delta usage, track cache_creation_tokens"
```

---

### Task 4: 更新 Schema

**Files:**
- Modify: `backend/app/schemas/usage.py`

- [ ] **Step 1: 修改 `UsageRecordResponse`**

```python
class UsageRecordResponse(BaseModel):
    id: int
    model: str
    input_tokens: int = Field(..., alias="inputTokens")
    cache_read_tokens: int = Field(..., alias="cacheReadTokens")
    cache_creation_tokens: int = Field(..., alias="cacheCreationTokens")
    output_tokens: int = Field(..., alias="outputTokens")
    cost_cents: int = Field(..., alias="costCents")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: 提交**

```bash
git add backend/app/schemas/usage.py
git commit -m "refactor(schema): update UsageRecordResponse with cache fields, camelCase aliases"
```

---

### Task 5: 数据库迁移

**Files:**
- Create: `backend/alembic/versions/xxxx_rename_and_add_cache_columns.py`（Alembic 自动生成）

- [ ] **Step 1: 生成迁移**

```bash
cd backend && uv run alembic revision --autogenerate -m "rename token columns and add cache fields"
```

- [ ] **Step 2: 检查生成的迁移文件**

确认 upgrade/downgrade 包含正确操作：
- `rename_column` request_tokens → input_tokens
- `rename_column` response_tokens → output_tokens
- `drop_column` total_tokens
- `add_column` cache_read_tokens
- `add_column` cache_creation_tokens

如果空迁移（SQLite `--autogenerate` 可能不支持 rename/drop），手动替换为：

```python
def upgrade() -> None:
    op.alter_column("usage_records", "request_tokens", new_column_name="input_tokens")
    op.alter_column("usage_records", "response_tokens", new_column_name="output_tokens")
    op.drop_column("usage_records", "total_tokens")
    op.add_column("usage_records", sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("usage_records", sa.Column("cache_creation_tokens", sa.Integer(), nullable=False, server_default="0"))

def downgrade() -> None:
    op.alter_column("usage_records", "input_tokens", new_column_name="request_tokens")
    op.alter_column("usage_records", "output_tokens", new_column_name="response_tokens")
    op.add_column("usage_records", sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.drop_column("usage_records", "cache_creation_tokens")
    op.drop_column("usage_records", "cache_read_tokens")
```

- [ ] **Step 3: 运行迁移**

```bash
cd backend && uv run alembic upgrade head
```
Expected: 迁移成功

- [ ] **Step 4: 运行后端测试**

```bash
cd backend && uv run pytest -v
```
Expected: 所有测试通过

- [ ] **Step 5: 提交**

```bash
git add backend/alembic/
git commit -m "migrate: rename token columns, drop total_tokens, add cache fields"
```

---

### Task 6: 前端 — 全局 formatDate 加时间

**Files:**
- Modify: `frontend/lib/utils/format.ts`

- [ ] **Step 1: 修改 `formatDate`**

将 `toLocaleDateString` 改为 `toLocaleString`，增加时分秒：

```typescript
export function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
// 输出示例: "2026/06/06 14:32:05"
```

- [ ] **Step 2: 提交**

```bash
git add frontend/lib/utils/format.ts
git commit -m "feat(frontend): add hh:mm:ss to formatDate globally"
```

---

### Task 7: 前端 — 更新 UsageRecord 接口

**Files:**
- Modify: `frontend/lib/api/usage.ts`

- [ ] **Step 1: 修改 `UsageRecord` 接口**

```typescript
export interface UsageRecord {
  id: number;
  model: string;
  inputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  outputTokens: number;
  costCents: number;
  createdAt: string;
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/lib/api/usage.ts
git commit -m "refactor(frontend): update UsageRecord interface with cache fields"
```

---

### Task 8: 前端 — 更新调用记录表

**Files:**
- Modify: `frontend/app/(user)/usage/page.tsx`

- [ ] **Step 1: 修改表头和列绑定**

将调用记录表格的表头从 `时间 | 模型 | 请求 | 响应 | 总计 | 费用` 改为 `时间 | 模型 | 输入 | 缓存读 | 缓存创建 | 输出 | 费用`，并更新对应的数据绑定。

替换第 157-162 行的表头：

```tsx
<thead>
  <tr className="border-b border-neutral-border text-left text-neutral-text-secondary">
    <th className="py-2 font-medium">时间</th>
    <th className="py-2 font-medium">模型</th>
    <th className="py-2 font-medium text-right">输入</th>
    <th className="py-2 font-medium text-right">缓存读</th>
    <th className="py-2 font-medium text-right">缓存创建</th>
    <th className="py-2 font-medium text-right">输出</th>
    <th className="py-2 font-medium text-right">费用</th>
  </tr>
</thead>
```

替换第 166-187 行的数据行：

```tsx
{history.records.map((r) => (
  <tr
    key={r.id}
    className="border-b border-neutral-border last:border-0"
  >
    <td className="py-2 text-neutral-text-primary">
      {formatDate(r.createdAt)}
    </td>
    <td className="py-2 font-mono text-xs">{r.model}</td>
    <td className="py-2 text-right font-mono">
      {formatTokens(r.inputTokens)}
    </td>
    <td className="py-2 text-right font-mono">
      {formatTokens(r.cacheReadTokens)}
    </td>
    <td className="py-2 text-right font-mono">
      {formatTokens(r.cacheCreationTokens)}
    </td>
    <td className="py-2 text-right font-mono">
      {formatTokens(r.outputTokens)}
    </td>
    <td className="py-2 text-right font-mono">
      {formatPrice(r.costCents)}
    </td>
  </tr>
))}
```

- [ ] **Step 2: 运行前端检查**

```bash
cd frontend && npm run build
```
Expected: 无编译错误

- [ ] **Step 3: 提交**

```bash
git add frontend/app/\(user\)/usage/page.tsx
git commit -m "feat(frontend): split token display into input/cache-read/cache-create/output columns"
```

---

### Task 9: 运行完整验证

- [ ] **Step 1: 后端测试**

```bash
cd backend && uv run pytest -v
```
Expected: 所有测试通过

- [ ] **Step 2: 前端构建**

```bash
cd frontend && npm run build
```
Expected: 构建成功

- [ ] **Step 3: 提交**

```bash
git add -A
git diff --cached --stat
# 确认没有遗漏
git commit -m "chore: final verification after call records optimization"
```

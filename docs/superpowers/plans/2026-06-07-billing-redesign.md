# 计费系统重构 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `proxy.py` 的"预扣 → 流式 → 同步结算"改成"流式 → 写 pending_billing → 后台 worker 异步计费"，修 channel_multiplier bug 和 cache_creation 漏算 bug，删老 `_settle_billing`。

**Architecture:** Alembic 迁移新增 `pending_billing` 表 + `usage_records.channel_id` 列。新建 `app/services/billing/{compute,pending,settle,worker}.py` 模块。`proxy.py` 的 `billing_stream` finally 块从调 `_settle_billing` 改为调 `pending.write_pending_billing`。`api/app.py` lifespan 启动 `BillingWorker` 后台 task，每 30s 扫一次未结算的 pending，串行化扣钱 + 写三表。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy async (asyncpg + aiosqlite) / Alembic / pytest / pytest-asyncio / Next.js 15 / React 19 / TanStack Query

---

## 文件结构

| 文件 | 状态 | 职责 |
|------|------|------|
| `backend/app/models/pending_billing.py` | 新建 | `PendingBilling` ORM |
| `backend/app/models/__init__.py` | 改 | 导出 `PendingBilling` |
| `backend/app/models/usage.py` | 改 | `UsageRecord` 加 `channel_id` |
| `backend/alembic/versions/<rev>_add_pending_billing.py` | 新建 | 建表 + 加列 |
| `backend/app/services/billing/__init__.py` | 新建 | 包标记 |
| `backend/app/services/billing/compute.py` | 新建 | `compute_cost` + `compute_costs_for_pending` |
| `backend/app/services/billing/pending.py` | 新建 | `write_pending_billing` + `claim_pending_batch` |
| `backend/app/services/billing/settle.py` | 新建 | `settle_one` |
| `backend/app/services/billing/worker.py` | 新建 | `BillingWorker` 类 |
| `backend/app/routers/proxy.py` | 改 | 删 pre-reserve / `_settle_billing` / finally 写 pending |
| `backend/app/routers/usage.py` | 改 | `/usage/history` 返回 `channelId/Name` |
| `backend/app/schemas/usage.py` | 改 | `UsageRecordResponse` 加 `channelId/Name` |
| `backend/api/app.py` | 改 | lifespan 启动/停止 `BillingWorker` |
| `frontend/lib/api/usage.ts` | 改 | `UsageRecord` 加 `channelId/channelName` |
| `frontend/app/(user)/usage/page.tsx` | 改 | 表格新增"渠道"列 |
| `backend/tests/services/billing/test_compute.py` | 新建 | `compute_cost` 单元测试 |
| `backend/tests/services/billing/test_pending.py` | 新建 | `write` / `claim` 单元测试 |
| `backend/tests/services/billing/test_settle.py` | 新建 | `settle_one` 单元测试 |
| `backend/tests/services/billing/test_worker.py` | 新建 | `BillingWorker` 单元测试 |
| `backend/tests/integration/test_billing_flow.py` | 新建 | 端到端测试 |

---

### Task 1: 新增 `PendingBilling` ORM 模型

**Files:**
- Create: `backend/app/models/pending_billing.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: 写 `PendingBilling` 模型**

`backend/app/models/pending_billing.py`:

```python
"""PendingBilling ORM — async billing queue between proxy and worker."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """Cross-dialect UUID (PostgreSQL native, SQLite CHAR(36))."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class PendingBilling(Base):
    __tablename__ = "pending_billing"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), unique=True, nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    api_key_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("api_keys.id"), nullable=False
    )
    model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("models.id"), nullable=False
    )
    channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("channel_configs.id"), nullable=False
    )
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id"), nullable=False
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )  # pending | settled | dead
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 2: 注册到 `app/models/__init__.py`**

`backend/app/models/__init__.py` 末尾加一行:

```python
from app.models.pending_billing import PendingBilling  # noqa: F401
```

- [ ] **Step 3: 验证导入不报错**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run python -c "from app.models import PendingBilling; print(PendingBilling)"
```

Expected: 打印 `<class 'app.models.pending_billing.PendingBilling'>`，无 traceback。

- [ ] **Step 4: 提交**

```bash
git add backend/app/models/pending_billing.py backend/app/models/__init__.py
git commit -m "feat(model): add PendingBilling ORM for async billing queue"
```

---

### Task 2: `UsageRecord.channel_id` 字段

**Files:**
- Modify: `backend/app/models/usage.py`

- [ ] **Step 1: 加 `channel_id` 字段**

`backend/app/models/usage.py` 加 import 和字段:

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
    channel_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("channel_configs.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
```

- [ ] **Step 2: 验证导入**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run python -c "from app.models.usage import UsageRecord; print(UsageRecord.channel_id)"
```

Expected: `<sqlalchemy.orm.attributes.InstrumentedAttribute object at 0x...>`

- [ ] **Step 3: 提交**

```bash
git add backend/app/models/usage.py
git commit -m "feat(model): add channel_id to UsageRecord"
```

---

### Task 3: Alembic 迁移 — `pending_billing` + `usage_records.channel_id`

**Files:**
- Create: `backend/alembic/versions/<rev>_add_pending_billing_and_channel_id.py`

- [ ] **Step 1: 找到下一个 revision id**

```bash
ls /Users/wangdecheng/ai/claude-gateway/backend/alembic/versions/ | grep -E "^[a-f0-9]{12}" | sort | tail -3
```

记下最后一个 rev id，比如 `c08f886da667`。本任务新 rev 用 `add_pending_billing_<日期>` 形式（不是 hash），保持项目里既有非 hash 命名（如 `03fa53dc7d91_add_channel_config_name.py`）的兼容性也用 hash。**用 hash**：跑下面的命令生成。

- [ ] **Step 2: 生成 migration 文件**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && \
uv run alembic revision -m "add pending_billing and usage_records.channel_id"
```

输出形如 `Generating /Users/wangdecheng/.../alembic/versions/<hash>_add_pending_billing_and_usage_records_channel_id.py ... done`

- [ ] **Step 3: 替换 upgrade / downgrade 内容**

打开生成的文件。`upgrade()` 替换为:

```python
def upgrade() -> None:
    # pending_billing table
    op.create_table(
        "pending_billing",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("request_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"]),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["channel_configs.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
    )
    op.create_index("ix_pending_billing_request_id", "pending_billing", ["request_id"], unique=True)
    op.create_index(
        "ix_pending_billing_pending",
        "pending_billing",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # usage_records.channel_id
    op.add_column("usage_records", sa.Column("channel_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_usage_records_channel_id",
        "usage_records",
        "channel_configs",
        ["channel_id"],
        ["id"],
    )
    op.create_index("ix_usage_records_channel_id", "usage_records", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_channel_id", table_name="usage_records")
    op.drop_constraint("fk_usage_records_channel_id", "usage_records", type_="foreignkey")
    op.drop_column("usage_records", "channel_id")
    op.drop_index("ix_pending_billing_pending", table_name="pending_billing")
    op.drop_index("ix_pending_billing_request_id", table_name="pending_billing")
    op.drop_table("pending_billing")
```

- [ ] **Step 4: 升级到 head**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run alembic upgrade head
```

Expected: `Running upgrade <prev> -> <new>, add pending billing and usage records channel id`

- [ ] **Step 5: 验证 schema**

```bash
docker exec cloude-gateway-postgres psql -U high_api -d high_api -c "\d pending_billing"
```

Expected: 列出所有列，含 `status`, `retry_count`, `last_error`, `settled_at`。

- [ ] **Step 6: 验证 usage_records.channel_id**

```bash
docker exec cloude-gateway-postgres psql -U high_api -d high_api -c "\d usage_records"
```

Expected: 列里出现 `channel_id | integer |` (nullable)。

- [ ] **Step 7: 提交**

```bash
git add backend/alembic/versions/
git commit -m "feat(migration): add pending_billing table and usage_records.channel_id"
```

---

### Task 4: `compute.py` — `compute_cost` 函数 (TDD)

**Files:**
- Create: `backend/app/services/billing/__init__.py` (空)
- Create: `backend/app/services/billing/compute.py`
- Create: `backend/tests/services/billing/__init__.py` (空)
- Create: `backend/tests/services/billing/test_compute.py`

- [ ] **Step 1: 写失败的测试**

`backend/tests/services/billing/test_compute.py`:

```python
"""Unit tests for billing compute_cost."""

import math


def test_compute_cost_basic_input_output():
    """Pure input + output, multiplier 1.0."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,   # ¥0.015 / 1K
        output_price_micro_yuan=75000,  # ¥0.075 / 1K
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=15000,
        channel_multiplier=1.0,
    )
    # (1*15000 + 1*75000) * 1.0 = 90000 micro-yuan = 9 cents
    assert cost == 9


def test_compute_cost_with_multiplier():
    """channel_multiplier scales the result."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=0,
        output_price_micro_yuan=75000,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=0,
        channel_multiplier=0.5,
    )
    # 1*75000 * 0.5 = 37500 micro-yuan = 3.75 cents → ceil = 4
    assert cost == 4


def test_compute_cost_cache_creation_charged_at_input_price():
    """cache_creation uses its own price param (caller passes input_price)."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=2000,  # 2K cache_creation
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=15000,  # passed explicitly
        channel_multiplier=1.0,
    )
    # 2 * 15000 = 30000 micro-yuan = 3 cents
    assert cost == 3


def test_compute_cost_cache_read_at_own_price():
    """cache_read uses cache_read_price (often 0)."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=5000,
        cache_creation_tokens=0,
        input_price_micro_yuan=0,
        output_price_micro_yuan=0,
        cache_read_price_micro_yuan=3000,  # ¥0.003 / 1K
        cache_creation_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    # 5 * 3000 = 15000 micro-yuan = 1.5 → ceil = 2
    assert cost == 2


def test_compute_cost_zero_tokens_returns_zero():
    """All zero tokens → zero cost."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=75000,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=15000,
        channel_multiplier=1.0,
    )
    assert cost == 0


def test_compute_cost_rounds_up():
    """Fractional cents round up to next whole cent."""
    from app.services.billing.compute import compute_cost

    cost = compute_cost(
        input_tokens=1,  # tiny
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        input_price_micro_yuan=15000,
        output_price_micro_yuan=0,
        cache_read_price_micro_yuan=0,
        cache_creation_price_micro_yuan=0,
        channel_multiplier=1.0,
    )
    # 1/1000 * 15000 = 15 micro-yuan = 0.0015 cents → ceil = 1
    assert cost == 1
```

- [ ] **Step 2: 跑测试，验证失败**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_compute.py -v
```

Expected: 6 个 `ModuleNotFoundError: No module named 'app.services.billing.compute'`。

- [ ] **Step 3: 创建 billing 包和 compute.py**

`backend/app/services/billing/__init__.py` — 空文件。
`backend/tests/services/billing/__init__.py` — 空文件。

`backend/app/services/billing/compute.py`:

```python
"""Cost computation for the async billing pipeline.

Prices are in micro-yuan per 1K tokens. Result is in cents (向上取整).
"""

import math


def compute_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    input_price_micro_yuan: int,
    output_price_micro_yuan: int,
    cache_read_price_micro_yuan: int,
    cache_creation_price_micro_yuan: int,
    channel_multiplier: float = 1.0,
) -> int:
    """Compute the cost in cents for a single request, rounding up.

    The caller is responsible for setting ``cache_creation_price_micro_yuan``
    to whatever they want to charge (industry default: input_price).
    """
    base = (
        input_tokens / 1000.0 * input_price_micro_yuan
        + output_tokens / 1000.0 * output_price_micro_yuan
        + cache_read_tokens / 1000.0 * cache_read_price_micro_yuan
        + cache_creation_tokens / 1000.0 * cache_creation_price_micro_yuan
    )
    return max(0, math.ceil(base * channel_multiplier / 10_000))
```

- [ ] **Step 4: 跑测试，验证通过**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_compute.py -v
```

Expected: 6 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/billing/ backend/tests/services/billing/
git commit -m "feat(billing): add compute_cost with cache_creation and channel_multiplier"
```

---

### Task 5: `pending.py` — `write_pending_billing` (TDD)

**Files:**
- Create: `backend/app/services/billing/pending.py`
- Create: `backend/tests/services/billing/test_pending.py`

- [ ] **Step 1: 写失败的测试**

`backend/tests/services/billing/test_pending.py`:

```python
"""Unit tests for pending_billing write/claim operations."""

import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.user import User


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Seed minimal fixtures
        user = User(id=1, email="t@e.com", password_hash="x", balance=1000, role="user", status="active")
        provider = Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active")
        model = Model(id=1, public_name="m", provider_id=1, provider_model_id="m", input_price=15000, output_price=75000, status="active")
        channel = ChannelConfig(id=1, model_id=1, provider_id=1, multiplier=1.0, is_default=True, status="active")
        api_key = ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active")
        session.add_all([user, provider, model, channel, api_key])
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_write_pending_billing_inserts_row(db_session: AsyncSession):
    """write_pending_billing returns a PendingBilling with status='pending' and the right fields."""
    from app.services.billing.pending import write_pending_billing

    request_id = uuid.uuid4()
    pb = await write_pending_billing(
        db_session,
        request_id=request_id,
        user_id=1,
        api_key_id=1,
        model_id=1,
        channel_id=1,
        provider_id=1,
        input_tokens=100,
        output_tokens=200,
        cache_read_tokens=50,
        cache_creation_tokens=0,
    )
    await db_session.commit()

    assert isinstance(pb, PendingBilling)
    assert pb.request_id == request_id
    assert pb.status == "pending"
    assert pb.retry_count == 0
    assert pb.input_tokens == 100
    assert pb.output_tokens == 200
    assert pb.cache_read_tokens == 50
    assert pb.last_error is None
    assert pb.settled_at is None


@pytest.mark.asyncio
async def test_write_pending_billing_idempotent_on_request_id(db_session: AsyncSession):
    """Same request_id → raises (UNIQUE violation)."""
    import sqlalchemy.exc
    from app.services.billing.pending import write_pending_billing

    request_id = uuid.uuid4()
    await write_pending_billing(
        db_session,
        request_id=request_id, user_id=1, api_key_id=1,
        model_id=1, channel_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    await db_session.commit()
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await write_pending_billing(
            db_session,
            request_id=request_id, user_id=1, api_key_id=1,
            model_id=1, channel_id=1, provider_id=1,
            input_tokens=10, output_tokens=10,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        await db_session.commit()
```

- [ ] **Step 2: 跑测试，验证失败**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_pending.py -v
```

Expected: 2 个 `ModuleNotFoundError`。

- [ ] **Step 3: 实现 `write_pending_billing`**

`backend/app/services/billing/pending.py`:

```python
"""Pending billing queue — write from proxy, claim from worker."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_billing import PendingBilling


async def write_pending_billing(
    db: AsyncSession,
    *,
    request_id: uuid.UUID,
    user_id: int,
    api_key_id: int,
    model_id: int,
    channel_id: int,
    provider_id: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> PendingBilling:
    """Insert a pending_billing row. Caller owns the transaction.

    The ``request_id`` is UNIQUE — duplicate writes raise IntegrityError.
    """
    pb = PendingBilling(
        request_id=request_id,
        user_id=user_id,
        api_key_id=api_key_id,
        model_id=model_id,
        channel_id=channel_id,
        provider_id=provider_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        status="pending",
        retry_count=0,
    )
    db.add(pb)
    await db.flush()
    return pb
```

- [ ] **Step 4: 跑测试，验证通过**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_pending.py -v
```

Expected: 2 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/billing/pending.py backend/tests/services/billing/test_pending.py
git commit -m "feat(billing): add write_pending_billing"
```

---

### Task 6: `pending.py` — `claim_pending_batch` (TDD)

**Files:**
- Modify: `backend/app/services/billing/pending.py`
- Modify: `backend/tests/services/billing/test_pending.py`

- [ ] **Step 1: 加失败的测试**

`backend/tests/services/billing/test_pending.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_claim_pending_batch_returns_only_old_pending(db_session: AsyncSession):
    """claim_pending_batch skips recent pending rows (in-flight window)."""
    from app.services.billing.pending import claim_pending_batch, write_pending_billing

    # Recent row (created_at = now) — should be SKIPPED
    await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, channel_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    await db_session.commit()

    claimed = await claim_pending_batch(db_session, max_age_seconds=5, limit=10)
    assert claimed == []


@pytest.mark.asyncio
async def test_claim_pending_batch_returns_old_pending(db_session: AsyncSession):
    """claim_pending_batch returns rows older than max_age."""
    from datetime import timedelta
    from app.services.billing.pending import claim_pending_batch, write_pending_billing

    pb = await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, channel_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    # Backdate created_at to 10s ago
    pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await db_session.commit()

    claimed = await claim_pending_batch(db_session, max_age_seconds=5, limit=10)
    assert len(claimed) == 1
    assert claimed[0].id == pb.id


@pytest.mark.asyncio
async def test_claim_pending_batch_skips_settled_and_dead(db_session: AsyncSession):
    """Only status='pending' rows are claimed."""
    from datetime import timedelta
    from app.services.billing.pending import claim_pending_batch, write_pending_billing

    # Insert one pending + one settled
    pb_pending = await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, channel_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    pb_settled = await write_pending_billing(
        db_session,
        request_id=uuid.uuid4(), user_id=1, api_key_id=1,
        model_id=1, channel_id=1, provider_id=1,
        input_tokens=10, output_tokens=10,
        cache_read_tokens=0, cache_creation_tokens=0,
    )
    pb_pending.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    pb_settled.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    pb_settled.status = "settled"
    await db_session.commit()

    claimed = await claim_pending_batch(db_session, max_age_seconds=5, limit=10)
    assert len(claimed) == 1
    assert claimed[0].id == pb_pending.id
```

- [ ] **Step 2: 跑测试，验证失败**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_pending.py -v
```

Expected: 3 个 FAIL（最后 3 个），错误 `function 'claim_pending_batch' not defined`。

- [ ] **Step 3: 实现 `claim_pending_batch`**

`backend/app/services/billing/pending.py` 末尾追加:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def claim_pending_batch(
    db: AsyncSession,
    *,
    max_age_seconds: int = 5,
    limit: int = 100,
) -> list[PendingBilling]:
    """Return a batch of old pending rows for the worker to settle.

    The caller is expected to be inside a transaction. We use SELECT ... FOR
    UPDATE SKIP LOCKED so that future multi-worker setups can claim disjoint
    batches. After the worker's transaction commits, the rows are released.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    stmt = (
        select(PendingBilling)
        .where(
            PendingBilling.status == "pending",
            PendingBilling.created_at < cutoff,
        )
        .order_by(PendingBilling.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

- [ ] **Step 4: 跑测试，验证通过**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_pending.py -v
```

Expected: 5 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/billing/pending.py backend/tests/services/billing/test_pending.py
git commit -m "feat(billing): add claim_pending_batch with FOR UPDATE SKIP LOCKED"
```

---

### Task 7: `compute_costs_for_pending` (TDD)

**Files:**
- Modify: `backend/app/services/billing/compute.py`
- Modify: `backend/tests/services/billing/test_compute.py`

- [ ] **Step 1: 加失败的测试**

`backend/tests/services/billing/test_compute.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_compute_costs_for_pending_loads_prices_and_multiplier():
    """compute_costs_for_pending loads channel.multiplier and model prices, calls compute_cost."""
    import os
    import sys
    import uuid
    from datetime import datetime, timezone

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.database import Base
    from app.models.api_key import ApiKey
    from app.models.model import ChannelConfig, Model
    from app.models.pending_billing import PendingBilling
    from app.models.provider import Provider
    from app.models.user import User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Seed with multiplier=0.5 channel
        session.add(User(id=1, email="t@e.com", password_hash="x", balance=1000, role="user", status="active"))
        session.add(Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active"))
        session.add(Model(id=1, public_name="m", provider_id=1, provider_model_id="m", input_price=15000, output_price=75000, cache_read_price=0, status="active"))
        session.add(ChannelConfig(id=1, model_id=1, provider_id=1, multiplier=0.5, is_default=True, status="active"))
        session.add(ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"))
        await session.flush()
        pb = PendingBilling(
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
            status="pending",
        )
        session.add(pb)
        await session.commit()

        from app.services.billing.compute import compute_costs_for_pending
        cost = await compute_costs_for_pending(pb, session)
        # (1*15000 + 1*75000) * 0.5 = 45000 micro-yuan = 4.5 → ceil = 5
        assert cost == 5
    await engine.dispose()
```

- [ ] **Step 2: 跑测试，验证失败**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_compute.py::test_compute_costs_for_pending_loads_prices_and_multiplier -v
```

Expected: 1 FAIL，`function 'compute_costs_for_pending' not defined`。

- [ ] **Step 3: 实现 `compute_costs_for_pending`**

`backend/app/services/billing/compute.py` 末尾追加:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


async def compute_costs_for_pending(
    pending: "PendingBilling",  # noqa: F821 — forward ref
    db: AsyncSession,
) -> int:
    """Load channel multiplier and model prices, then call compute_cost.

    cache_creation_price is set to input_price (industry default).
    """
    from app.models.model import ChannelConfig, Model
    from app.models.pending_billing import PendingBilling

    channel = await db.scalar(
        select(ChannelConfig).where(ChannelConfig.id == pending.channel_id)
    )
    model = await db.scalar(select(Model).where(Model.id == pending.model_id))
    return compute_cost(
        input_tokens=pending.input_tokens,
        output_tokens=pending.output_tokens,
        cache_read_tokens=pending.cache_read_tokens,
        cache_creation_tokens=pending.cache_creation_tokens,
        input_price_micro_yuan=model.input_price,
        output_price_micro_yuan=model.output_price,
        cache_read_price_micro_yuan=model.cache_read_price,
        cache_creation_price_micro_yuan=model.input_price,
        channel_multiplier=channel.multiplier,
    )
```

- [ ] **Step 4: 跑测试，验证通过**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_compute.py -v
```

Expected: 7 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/billing/compute.py backend/tests/services/billing/test_compute.py
git commit -m "feat(billing): add compute_costs_for_pending helper"
```

---

### Task 8: `settle.py` — `settle_one` (TDD)

**Files:**
- Create: `backend/app/services/billing/settle.py`
- Create: `backend/tests/services/billing/test_settle.py`

- [ ] **Step 1: 写失败的测试**

`backend/tests/services/billing/test_settle.py`:

```python
"""Unit tests for settle_one — happy path and failure paths."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.billing_record import BillingRecord
from app.models.model import ChannelConfig, Model
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.request_log import RequestLog
from app.models.usage import UsageRecord
from app.models.user import User


@pytest.fixture
async def seeded_db():
    """Yield (session, refs) for an in-memory DB with user, model, channel seeded."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    refs = {}
    async with factory() as session:
        user = User(id=1, email="t@e.com", password_hash="x", balance=10000, role="user", status="active")
        provider = Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active")
        model = Model(id=1, public_name="m", provider_id=1, provider_model_id="m", input_price=15000, output_price=75000, cache_read_price=0, status="active")
        channel = ChannelConfig(id=1, model_id=1, provider_id=1, multiplier=1.0, is_default=True, status="active")
        api_key = ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active")
        session.add_all([user, provider, model, channel, api_key])
        await session.commit()
        refs = {"user_id": 1, "api_key_id": 1, "model_id": 1, "channel_id": 1, "provider_id": 1}
        yield session, refs

    await engine.dispose()


@pytest.mark.asyncio
async def test_settle_one_deducts_balance_and_writes_three_tables(seeded_db):
    """Happy path: balance deducted, request_logs/billing_records/usage_records all written, status='settled'."""
    session, refs = seeded_db
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.settle import settle_one

    pb = await write_pending_billing(
        session,
        request_id=uuid.uuid4(),
        user_id=refs["user_id"],
        api_key_id=refs["api_key_id"],
        model_id=refs["model_id"],
        channel_id=refs["channel_id"],
        provider_id=refs["provider_id"],
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    await session.commit()

    await settle_one(session, pb)
    await session.commit()

    # Balance: started 10000 cents, cost = (15000+75000)/10000 = 9 cents
    user = await session.get(User, 1)
    assert user.balance == 10000 - 9

    # pending_billing marked settled
    await session.refresh(pb)
    assert pb.status == "settled"
    assert pb.settled_at is not None

    # request_logs
    rl_result = await session.execute(select(RequestLog).where(RequestLog.request_id == pb.request_id))
    rl = rl_result.scalar_one()
    assert rl.user_id == 1
    assert rl.cost_cents == 9
    assert rl.channel_id == 1
    assert rl.status == "success"

    # billing_records (1:1 with request_log)
    br_result = await session.execute(select(BillingRecord).where(BillingRecord.request_log_id == rl.id))
    br = br_result.scalar_one()
    assert br.amount_cents == 9
    assert br.balance_after_cents == 10000 - 9

    # usage_records
    ur_result = await session.execute(select(UsageRecord).where(UsageRecord.user_id == 1))
    ur = ur_result.scalar_one()
    assert ur.cost_cents == 9
    assert ur.channel_id == 1
    assert ur.input_tokens == 1000


@pytest.mark.asyncio
async def test_settle_one_increments_retry_on_failure(seeded_db):
    """If compute throws, retry_count increments, status stays 'pending'."""
    session, refs = seeded_db
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.settle import settle_one

    pb = await write_pending_billing(
        session,
        request_id=uuid.uuid4(),
        user_id=refs["user_id"],
        api_key_id=refs["api_key_id"],
        model_id=refs["model_id"],
        channel_id=refs["channel_id"],
        provider_id=refs["provider_id"],
        input_tokens=1000,
        output_tokens=1000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    await session.commit()

    # Force a failure by deleting the channel row
    ch = await session.get(ChannelConfig, 1)
    await session.delete(ch)
    await session.commit()

    with pytest.raises(Exception):
        await settle_one(session, pb)
    await session.rollback()

    await session.refresh(pb)
    assert pb.retry_count == 1
    assert pb.status == "pending"
    assert pb.last_error is not None
```

如果 `RequestLog` 没有 `request_id` 列（只有 `id`），把 `RequestLog.request_id == pb.request_id` 改成 `RequestLog.id == rl.id` 等价形式。**先看 `backend/app/models/request_log.py` 的列名确认**。

- [ ] **Step 2: 跑测试，验证失败**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_settle.py -v
```

Expected: 2 个 FAIL（`function 'settle_one' not defined`）。

- [ ] **Step 3: 看 `RequestLog` 的列名**

```bash
cat /Users/wangdecheng/ai/claude-gateway/backend/app/models/request_log.py
```

记下 PK 列名（`id` 或 `request_id`）。如果 PK 是 `id` 而 `request_id` 是 UNIQUE 列，把测试里的 `RequestLog.request_id == pb.request_id` 改成 `RequestLog.id == rl.id` 等价形式。最简单：从 pending 反查 request_log 时用 `RequestLog.id == ?`，但 `settle_one` 写完 request_log 才会返回 ID。**改用 `await session.flush()` 后 `pb.settled_at` 反查**——但这又脆。**最稳**：写一个 ORM helper `RequestLog.id == pb.id`（不，pb.id 是 pending_billing 的 id）。

如果 `RequestLog` 有 `request_id` 字段（UNIQUE），用 `RequestLog.request_id == pb.request_id`。读源码确认。

- [ ] **Step 4: 实现 `settle_one`**

`backend/app/services/billing/settle.py`:

```python
"""Settle one pending_billing row — deduct balance and write three audit tables."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_record import BillingRecord
from app.models.model import Model
from app.models.pending_billing import PendingBilling
from app.models.request_log import RequestLog
from app.models.usage import UsageRecord
from app.models.user import User
from app.services.billing.compute import compute_costs_for_pending

logger = logging.getLogger("cloude-gateway.billing.settle")


async def settle_one(db: AsyncSession, pending: PendingBilling) -> None:
    """Settle a single pending_billing row.

    Caller owns the transaction: success path commits, failure path rolls back.
    On any exception, the caller is expected to roll back AND increment
    retry_count on the pending row in a follow-up transaction.
    """
    cost = await compute_costs_for_pending(pending, db)
    model = await db.scalar(select(Model).where(Model.id == pending.model_id))

    # Lock user row
    user = await db.scalar(
        select(User).where(User.id == pending.user_id).with_for_update()
    )
    if user is None:
        raise RuntimeError(f"User {pending.user_id} not found")
    user.balance = user.balance - cost
    balance_after = user.balance

    # Write request_log
    rl = RequestLog(
        request_id=pending.request_id,
        user_id=pending.user_id,
        api_key_id=pending.api_key_id,
        model_id=pending.model_id,
        channel_id=pending.channel_id,
        provider_id=pending.provider_id,
        input_tokens=pending.input_tokens,
        output_tokens=pending.output_tokens,
        cache_read_tokens=pending.cache_read_tokens,
        cache_creation_tokens=pending.cache_creation_tokens,
        cost_cents=cost,
        status="success",
    )
    db.add(rl)
    await db.flush()  # need rl.id for BillingRecord FK

    # Write billing_record (1:1 with request_log)
    db.add(
        BillingRecord(
            user_id=pending.user_id,
            request_log_id=rl.id,
            amount_cents=cost,
            balance_after_cents=balance_after,
        )
    )

    # Write usage_record
    db.add(
        UsageRecord(
            user_id=pending.user_id,
            api_key_id=pending.api_key_id,
            model=model.public_name,
            input_tokens=pending.input_tokens,
            output_tokens=pending.output_tokens,
            cache_read_tokens=pending.cache_read_tokens,
            cache_creation_tokens=pending.cache_creation_tokens,
            cost_cents=cost,
            channel_id=pending.channel_id,
        )
    )

    # Mark pending settled
    pending.status = "settled"
    pending.settled_at = datetime.now(timezone.utc)


async def mark_retry(db: AsyncSession, pending: PendingBilling, exc: Exception) -> None:
    """Increment retry_count and record last_error. Caller commits."""
    pending.retry_count += 1
    pending.last_error = f"{type(exc).__name__}: {exc}"[:2000]


def max_retry_reached(pending: PendingBilling, max_retry: int = 3) -> bool:
    return pending.retry_count > max_retry
```

- [ ] **Step 5: 跑测试，验证通过**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_settle.py -v
```

Expected: 2 个 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/billing/settle.py backend/tests/services/billing/test_settle.py
git commit -m "feat(billing): add settle_one with balance deduction and three-table writes"
```

---

### Task 9: `worker.py` — `BillingWorker` (TDD)

**Files:**
- Create: `backend/app/services/billing/worker.py`
- Create: `backend/tests/services/billing/test_worker.py`

- [ ] **Step 1: 写失败的测试**

`backend/tests/services/billing/test_worker.py`:

```python
"""Unit tests for BillingWorker."""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.user import User


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all([
            User(id=1, email="t@e.com", password_hash="x", balance=10000, role="user", status="active"),
            Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active"),
            Model(id=1, public_name="m", provider_id=1, provider_model_id="m", input_price=15000, output_price=75000, cache_read_price=0, status="active"),
            ChannelConfig(id=1, model_id=1, provider_id=1, multiplier=1.0, is_default=True, status="active"),
            ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_and_settle_processes_old_pending(session_factory):
    """A pending row older than max_age gets settled by _scan_and_settle."""
    from datetime import datetime, timedelta, timezone
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        pb = await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 1

    async with session_factory() as session:
        u = await session.get(User, 1)
        assert u.balance == 10000 - 9  # cost 9 cents
        from sqlalchemy import select
        pbs = (await session.execute(select(PendingBilling))).scalars().all()
        assert pbs[0].status == "settled"


@pytest.mark.asyncio
async def test_scan_and_settle_skips_recent_pending(session_factory):
    """A pending row newer than max_age is skipped."""
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 0


@pytest.mark.asyncio
async def test_scan_and_settle_marks_dead_after_max_retry(session_factory):
    """A row whose settle fails max_retry+1 times is marked 'dead'."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        pb = await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        # Pre-bump retry_count past max
        await session.execute(
            update(PendingBilling).where(PendingBilling.id == pb.id).values(retry_count=3)
        )
        # Delete the channel to force a failure on settle
        ch = await session.get(ChannelConfig, 1)
        await session.delete(ch)
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 0  # couldn't settle

    async with session_factory() as session:
        from sqlalchemy import select
        pbs = (await session.execute(select(PendingBilling))).scalars().all()
        assert pbs[0].status == "dead"
```

- [ ] **Step 2: 跑测试，验证失败**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_worker.py -v
```

Expected: 3 个 FAIL（`BillingWorker` 不存在）。

- [ ] **Step 3: 实现 `BillingWorker`**

`backend/app/services/billing/worker.py`:

```python
"""Background worker — scans pending_billing and settles each row."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.pending_billing import PendingBilling
from app.services.billing.pending import claim_pending_batch
from app.services.billing.settle import mark_retry, max_retry_reached, settle_one

logger = logging.getLogger("cloude-gateway.billing.worker")


class BillingWorker:
    """In-process asyncio task that settles pending_billing rows.

    Run one per app instance. Uses FOR UPDATE SKIP LOCKED so that multi-worker
    setups are safe (each instance claims a disjoint batch).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        scan_interval: int = 30,
        max_age_seconds: int = 5,
        max_retry: int = 3,
        batch_limit: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.scan_interval = scan_interval
        self.max_age_seconds = max_age_seconds
        self.max_retry = max_retry
        self.batch_limit = batch_limit
        self._task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._run_loop(), name="billing-worker")

    async def stop(self) -> None:
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stopped:
            try:
                await self._scan_and_settle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("BillingWorker scan failed; will retry next interval")
            try:
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                raise

    async def _scan_and_settle(self) -> int:
        """Claim a batch and settle each row in its own short transaction.

        Returns the number of rows successfully settled.
        """
        # Phase 1: claim batch inside a short transaction
        async with self.session_factory() as db:
            claimed = await claim_pending_batch(
                db,
                max_age_seconds=self.max_age_seconds,
                limit=self.batch_limit,
            )
            claimed_ids = [pb.id for pb in claimed]
            await db.commit()  # release FOR UPDATE locks

        if not claimed_ids:
            return 0

        # Phase 2: settle each row independently
        settled_count = 0
        for pb_id in claimed_ids:
            try:
                async with self.session_factory() as db:
                    pb = await db.get(PendingBilling, pb_id)
                    if pb is None or pb.status != "pending":
                        continue
                    await settle_one(db, pb)
                    await db.commit()
                settled_count += 1
            except Exception as exc:
                logger.exception("settle_one failed for %s", pb_id)
                try:
                    async with self.session_factory() as db:
                        pb = await db.get(PendingBilling, pb_id)
                        if pb is None:
                            continue
                        if max_retry_reached(pb, self.max_retry):
                            pb.status = "dead"
                            await db.commit()
                            logger.error("PendingBilling %s marked dead after %d retries", pb_id, pb.retry_count)
                        else:
                            await mark_retry(db, pb, exc)
                except Exception:
                    logger.exception("mark_retry also failed for %s", pb_id)
        return settled_count
```

- [ ] **Step 4: 跑测试，验证通过**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/test_worker.py -v
```

Expected: 3 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/billing/worker.py backend/tests/services/billing/test_worker.py
git commit -m "feat(billing): add BillingWorker with scan-and-settle loop"
```

---

### Task 10: `proxy.py` 改造 — 删 pre-reserve / `_settle_billing` / finally 写 pending

**Files:**
- Modify: `backend/app/routers/proxy.py`

- [ ] **Step 1: 看当前 proxy.py 的关键段**

定位以下行（在 `proxy.py:28-32, 71-134, 235-253, 322-355` 范围）:

```python
MAX_COST_CENTS = 20_000
MIN_BALANCE_THRESHOLD_CENTS = 100
async def _settle_billing(...): ...
def _log_background_settlement_failure(...): ...
# 6 步 pre-reserve: estimated_cost / with_for_update / user.balance = ... / flush / commit
# finally: 调 settlement_task = asyncio.create_task(_settle_billing(...))
```

- [ ] **Step 2: 删 `MAX_COST_CENTS` 常量**

`backend/app/routers/proxy.py` 顶部:

```python
# Maximum cost cap: 200 RMB (20000 cents) per request
MAX_COST_CENTS = 20_000
# Minimum balance threshold for pre-flight check
MIN_BALANCE_THRESHOLD_CENTS = 10  # ¥0.10
```

- [ ] **Step 3: 删 `_settle_billing` 和 `_log_background_settlement_failure`**

整段删除 `async def _settle_billing(...)` 函数体和 `def _log_background_settlement_failure(task)` 函数体。

- [ ] **Step 4: 删 pre-reserve 6 步**

`backend/app/routers/proxy.py` 中 `── 6. Estimate max cost, pre-reserve ──` 整段:

```python
    # ── 6. Estimate max cost, pre-reserve ─────────────────────
    estimated_cost = int((body.max_tokens or 4096) * model.output_price / 1000 / 10000)
    estimated_cost = min(estimated_cost, MAX_COST_CENTS)

    # Lock user row
    lock_result = await db.execute(select(User.balance).where(User.id == user.id).with_for_update())
    locked_balance = lock_result.scalar_one()
    reserve_amount = min(estimated_cost, locked_balance)
    user.balance = locked_balance - reserve_amount
    await db.flush()
    await db.commit()
    trace_event(
        stage="billing",
        event="proxy.billing.reservation_committed",
        source="api",
        user_id=user.id,
        model=body.model,
        reserve_amount=reserve_amount,
    )
```

**整段删除**。

- [ ] **Step 5: 改 `billing_stream` finally 块**

把 finally 块从:

```python
        finally:
            # Extract usage from accumulated SSE events
            input_tokens = accumulated_usage["input_tokens"] or 100
            output_tokens = accumulated_usage["output_tokens"] or 0
            cache_read_tokens = accumulated_usage["cache_read_tokens"] or 0
            cache_creation_tokens = accumulated_usage["cache_creation_tokens"] or 0

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
            try:
                await asyncio.shield(settlement_task)
            except asyncio.CancelledError:
                settlement_task.add_done_callback(_log_background_settlement_failure)
                raise
```

改为:

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
                    channel_id=routed.db_channel_id,
                    provider_id=provider.id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "Failed to write pending_billing for user=%d model=%s",
                    user_id, body.model,
                )
```

- [ ] **Step 6: 删未用变量**

`billing_stream` 闭包里删 `reserve_amount`、删 `session_factory`（不再用）。

`backend/app/routers/proxy.py` 删:

```python
    session_factory = request.app.state.db_session_factory
```

- [ ] **Step 7: 删 unused imports**

`proxy.py` 顶部如果 `asyncio` 不再使用（没 `asyncio.create_task` / `asyncio.shield` 了），从 import 里删 `asyncio`。

如果 `uuid` 没在别处用，删它。

如果 `trace_event` 没被用，删 `from core.trace import trace_event`（pre-reserve 那块删了之后）.

- [ ] **Step 8: 启动后端，跑 /api/health**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run uvicorn server:app --port 8082 --reload &
sleep 3
curl -s http://localhost:8082/api/health
```

Expected: `{"status":"ok"}`.

然后 `kill %1`.

- [ ] **Step 9: 提交**

```bash
git add backend/app/routers/proxy.py
git commit -m "refactor(proxy): drop pre-reserve, write pending_billing in stream finally"
```

---

### Task 11: `api/app.py` lifespan 启动 `BillingWorker`

**Files:**
- Modify: `backend/api/app.py`

- [ ] **Step 1: 加 import + 启动/停止**

`backend/api/app.py` 的 `lifespan` 异步上下文里，`Initialize provider registry` 之后加:

```python
        # Start billing worker
        from app.services.billing.worker import BillingWorker
        app.state.billing_worker = BillingWorker(session_factory)
        await app.state.billing_worker.start()
        logger.info("BillingWorker started")
```

`yield` 之后 (`Shutdown` 段)，`reg.cleanup()` 之前加:

```python
        # Stop billing worker
        bw = getattr(app.state, "billing_worker", None)
        if bw is not None:
            await bw.stop()
            logger.info("BillingWorker stopped")
```

- [ ] **Step 2: 启动验证**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run uvicorn server:app --port 8082 --reload 2>&1 | head -50
```

Expected 看到: `Application startup complete` 和 `BillingWorker started`.

Ctrl-C 退出, Expected 看到: `BillingWorker stopped` 和 `Shutdown complete`.

- [ ] **Step 3: 提交**

```bash
git add backend/api/app.py
git commit -m "feat(lifespan): start BillingWorker in app startup, stop on shutdown"
```

---

### Task 12: `usage` schema + router 加 channel 字段

**Files:**
- Modify: `backend/app/schemas/usage.py`
- Modify: `backend/app/routers/usage.py`

- [ ] **Step 1: 加 schema 字段**

`backend/app/schemas/usage.py` 改 `UsageRecordResponse`:

```python
class UsageRecordResponse(BaseModel):
    id: int
    model: str
    input_tokens: int = Field(..., alias="inputTokens")
    cache_read_tokens: int = Field(..., alias="cacheReadTokens")
    cache_creation_tokens: int = Field(..., alias="cacheCreationTokens")
    output_tokens: int = Field(..., alias="outputTokens")
    cost_cents: int = Field(..., alias="costCents")
    channel_id: int | None = Field(None, alias="channelId")
    channel_name: str | None = Field(None, alias="channelName")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: 改 router 联表查 channel name**

`backend/app/routers/usage.py` 改 `usage_history` 的 records 拼装，加 LEFT JOIN 拿 channel_name。

`backend/app/services/usage_service.py` 改 `get_user_usage_history` 返回 (records, total, channels_dict):

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.channel_config import ChannelConfig

async def get_user_usage_history(
    db: AsyncSession, user: User, page: int = 1, page_size: int = 20,
) -> tuple[list, int, dict[int, str]]:
    count_result = await db.execute(
        select(func.count()).select_from(UsageRecord).where(UsageRecord.user_id == user.id)
    )
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        select(UsageRecord)
        .where(UsageRecord.user_id == user.id)
        .order_by(UsageRecord.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    records = list(result.scalars().all())

    # 批量查 channel name
    channel_ids = {r.channel_id for r in records if r.channel_id is not None}
    channel_map: dict[int, str] = {}
    if channel_ids:
        ch_result = await db.execute(
            select(ChannelConfig.id, ChannelConfig.channel_name)
            .where(ChannelConfig.id.in_(channel_ids))
        )
        channel_map = {row[0]: row[1] or "" for row in ch_result.all()}

    return records, total, channel_map
```

- [ ] **Step 3: 改 router 拼接 channelName**

`backend/app/routers/usage.py` 改 `usage_history`:

```python
    records, total, channel_map = await get_user_usage_history(
        db, user=user, page=page, page_size=page_size,
    )
    return {
        "records": [
            {
                "id": r.id,
                "model": r.model,
                "inputTokens": r.input_tokens,
                "cacheReadTokens": r.cache_read_tokens,
                "cacheCreationTokens": r.cache_creation_tokens,
                "outputTokens": r.output_tokens,
                "costCents": r.cost_cents,
                "channelId": r.channel_id,
                "channelName": channel_map.get(r.channel_id) if r.channel_id else None,
                "createdAt": r.created_at,
            }
            for r in records
        ],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }
```

- [ ] **Step 4: 跑现有 usage 测试（如果存在）**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/ -k "usage" -v
```

Expected: PASS（如果之前有 usage 测试）或"no tests ran"（如果没有，跳过）。

- [ ] **Step 5: 提交**

```bash
git add backend/app/schemas/usage.py backend/app/routers/usage.py backend/app/services/usage_service.py
git commit -m "feat(usage): return channel_id and channel_name in usage history"
```

---

### Task 13: 前端 `UsageRecord` 加 channel 字段

**Files:**
- Modify: `frontend/lib/api/usage.ts`

- [ ] **Step 1: 加字段**

`frontend/lib/api/usage.ts` 改 `UsageRecord` 接口:

```typescript
export interface UsageRecord {
  id: number;
  model: string;
  inputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  outputTokens: number;
  costCents: number;
  channelId: number | null;
  channelName: string | null;
  createdAt: string;
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/lib/api/usage.ts
git commit -m "feat(frontend): add channel fields to UsageRecord"
```

---

### Task 14: 前端 usage 表格加"渠道"列

**Files:**
- Modify: `frontend/app/(user)/usage/page.tsx`

- [ ] **Step 1: 看现有表头**

```bash
grep -n "cacheCreation\|cacheRead\|<th\|<td" /Users/wangdecheng/ai/claude-gateway/frontend/app/\(user\)/usage/page.tsx | head -20
```

确认表头顺序是 `时间 | 模型 | 输入 | 缓存读 | 缓存创建 | 输出 | 费用` 还是其他。

- [ ] **Step 2: 在"模型"列后加"渠道"列**

`<th>模型</th>` 之后加:

```tsx
<th className="px-3 py-2 text-left text-xs font-medium text-neutral-text-muted">渠道</th>
```

记录行 `<td>{record.model}</td>` 之后加:

```tsx
<td className="px-3 py-2 text-xs text-neutral-text-secondary">
  {record.channelName || record.channelId ? (
    <span className="font-mono">
      {record.channelName || `渠道 ${record.channelId}`}
    </span>
  ) : (
    <span className="text-neutral-text-muted">—</span>
  )}
</td>
```

- [ ] **Step 3: 跑 lint / build 验证**

```bash
cd /Users/wangdecheng/ai/claude-gateway/frontend && npm run lint
```

Expected: 0 errors (warnings OK).

```bash
npm run build
```

Expected: build 成功。

- [ ] **Step 4: 提交**

```bash
git add frontend/app/\(user\)/usage/page.tsx
git commit -m "feat(frontend): add 渠道 column to usage table"
```

---

### Task 15: 集成测试 — 端到端

**Files:**
- Create: `backend/tests/integration/test_billing_flow.py`

- [ ] **Step 1: 写集成测试**

`backend/tests/integration/test_billing_flow.py`:

```python
"""End-to-end billing flow: proxy stream → pending_billing → worker settle."""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import ApiKey
from app.models.model import ChannelConfig, Model
from app.models.pending_billing import PendingBilling
from app.models.provider import Provider
from app.models.usage import UsageRecord
from app.models.user import User


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add_all([
            User(id=1, email="t@e.com", password_hash="x", balance=10000, role="user", status="active"),
            Provider(id=1, name="p", api_base_url="http://x", auth_header="Authorization", adapter="openai-chat-completions", status="active"),
            Model(id=1, public_name="claude-opus-4-8", provider_id=1, provider_model_id="m", input_price=15000, output_price=75000, cache_read_price=0, status="active"),
            ChannelConfig(id=1, model_id=1, provider_id=1, multiplier=0.5, is_default=True, status="active"),
            ApiKey(id=1, user_id=1, name="k", key_prefix="sk-abc", key_hash="h", status="active"),
        ])
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_flow_stream_writes_pending_then_worker_settles(session_factory):
    """Insert pending_billing (simulating proxy stream-end), worker settles, balance deducted, multiplier applied."""
    import uuid
    from app.services.billing.pending import write_pending_billing
    from app.services.billing.worker import BillingWorker

    async with session_factory() as session:
        pb = await write_pending_billing(
            session,
            request_id=uuid.uuid4(),
            user_id=1, api_key_id=1, model_id=1, channel_id=1, provider_id=1,
            input_tokens=2000, output_tokens=1000,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        # Backdate to bypass in-flight window
        pb.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await session.commit()

    worker = BillingWorker(session_factory, max_age_seconds=5, max_retry=3, scan_interval=30)
    n = await worker._scan_and_settle()
    assert n == 1

    async with session_factory() as session:
        # Balance: 10000 - cost
        # cost = (2000/1000 * 15000 + 1000/1000 * 75000) * 0.5
        #      = (30000 + 75000) * 0.5 = 52500 micro-yuan = 5.25 cents → ceil = 6
        u = await session.get(User, 1)
        assert u.balance == 10000 - 6

        pbs = (await session.execute(select(PendingBilling))).scalars().all()
        assert pbs[0].status == "settled"

        urs = (await session.execute(select(UsageRecord).where(UsageRecord.user_id == 1))).scalars().all()
        assert len(urs) == 1
        assert urs[0].channel_id == 1
        assert urs[0].cost_cents == 6
        assert urs[0].input_tokens == 2000
        assert urs[0].output_tokens == 1000
```

- [ ] **Step 2: 跑测试**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/integration/test_billing_flow.py -v
```

Expected: 1 个 PASS.

- [ ] **Step 3: 跑全套 billing 测试**

```bash
cd /Users/wangdecheng/ai/claude-gateway/backend && uv run pytest tests/services/billing/ tests/integration/test_billing_flow.py -v
```

Expected: 全部 PASS（compute 7 + pending 5 + settle 2 + worker 3 + integration 1 = 18 个测试）。

- [ ] **Step 4: 提交**

```bash
git add backend/tests/integration/test_billing_flow.py
git commit -m "test(billing): add end-to-end integration test for async billing flow"
```

---

### Task 16: 部署后一次性补钱

**Files:** 无（操作步骤）

- [ ] **Step 1: 部署新代码（合并到 main + push + 触发部署）**

合并所有 task 提交，部署到生产。**注意**：部署前确认 alembic 迁移已运行（Task 3）。

- [ ] **Step 2: 验证 worker 启动**

部署后看启动日志: `BillingWorker started`. 

确认 `/api/health` 200。

- [ ] **Step 3: 跑补钱 SQL**

```bash
docker exec cloude-gateway-postgres psql -U high_api -d high_api -c "
UPDATE users SET balance = balance + 59873 WHERE id = 1;
"
```

Expected: `UPDATE 1`

- [ ] **Step 4: 验证补钱后余额**

```bash
docker exec cloude-gateway-postgres psql -U high_api -d high_api -c "
SELECT email, balance FROM users WHERE id = 1;
"
```

Expected: `287187910@qq.com | 98769` (38896 + 59873)。

- [ ] **Step 5: 跑 1-2 个真实调用验证**

通过 API key 调一次 `/v1/messages`，看:
- 前端 usage 页面立即看到一条新记录
- 30s 内 worker 处理，balance 减少
- /api/usage/history 返回的记录带 `channelName`

- [ ] **Step 6: 不需要单独 commit**

这是运维操作，不进 git。记录到内部 changelog / 部署日志即可。

---

## 自检清单（实施时核对）

- [ ] 所有 task 1-15 完成后，新代码已合并并部署
- [ ] `pytest tests/services/billing/ tests/integration/test_billing_flow.py` 18 个测试全 PASS
- [ ] `pytest tests/` 整体测试无 regression
- [ ] `uv run ruff check .` 无错误
- [ ] `npm run build` 前端构建成功
- [ ] 生产 alembic 迁移已应用
- [ ] 启动日志 `BillingWorker started` 出现
- [ ] 一次真实 API 调用后，pending_billing 30s 内被 settled
- [ ] balance 计算正确（multiplier 0.5 渠道按基线 50% 收费）
- [ ] 用户 id=1 已补 ¥598.73
- [ ] usage_history 接口返回 channelId/Name
- [ ] 前端 usage 表格显示"渠道"列

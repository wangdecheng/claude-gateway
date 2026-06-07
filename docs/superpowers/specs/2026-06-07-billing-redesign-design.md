# 计费系统重构 — 设计文档

**日期**: 2026-06-07
**状态**: 设计中

## 背景

当前 `proxy.py` 走"预扣 → 流式响应 → finally 结算"路径，存在 3 个导致余额计算错误的根因：

1. **`channel_multiplier=1.0` 写死**（`proxy.py:97`）：实际 admin 配置 0.5× 渠道按 1.0× 收，倍率 bug。
2. **结算异常时静默吞掉预扣**（`proxy.py:329-349`）：`_settle_billing` 在 `finally` 里用 `asyncio.shield` 等待，但只 catch `CancelledError`；其他异常会冒泡，`reserve` 永远不退还。
3. **`compute_cost` 不收 `cache_creation_tokens`**：用户用 prompt cache 时这部分不计费，长期是漏账风险。

实操案例：用户 id=1（287187910@qq.com）充值 ¥1000，当前余额 ¥388.96，usage_records 累计 ¥12.31，反推充值前余额 = **-¥598.73**。说明 ¥598.73 是在 4-7 小时内通过**无对应 usage_records 的扣款**消耗的，**根因是 #2**（失败结算吞预扣）。

## 目标

1. 取消 pre-reserve，改成"流结束 → 写 pending_billing → 后台 worker 计费"
2. 修 `channel_multiplier` bug（按真实 `channel_configs.multiplier` 计算）
3. 计费 `cache_creation_tokens`（按 `input_price` 收费，行业惯例）
4. `usage_records` 加 `channel_id` 列，前端展示
5. 最低余额门槛 100 cents → 10 cents（¥0.10）
6. 系统尚未上线，老 `_settle_billing` 直接删除，**不留兜底**

## 非目标

- 不做定时扫描式批处理（已选 worker 方案）
- 不做消息队列 / Redis（单实例足够）
- 不动 `request_logs` / `billing_records` schema（已正确）
- 不做"超过余额拒绝"功能（用户调用时已经按 0.1 元门槛预审；接受 worker 扣到负数）
- 不做 admin 通知（dead 状态仅靠 SQL 查询发现；如需未来再加）

## 数据流

```
[POST /v1/messages]
  1. require_api_key → (User, ApiKey)
  2. resolve model + channel + provider
  3. pre-flight: balance >= 10 cents (¥0.10)
  4. 透传 upstream stream, 累计 4 个 token 计数
  5. 流成功结束 → INSERT pending_billing (status='pending')
     - 含 input_tokens, output_tokens, cache_read_tokens,
       cache_creation_tokens, channel_id, provider_id, request_id
  6. 流异常（upstream 5xx / 连接断）→ 不写 pending → 不扣钱
  7. 返回响应

[Background worker - asyncio task, lifespan 内启动]
  每 30s 跑一次 _scan_and_settle:
    1. SELECT pending_billing
       WHERE status='pending' AND created_at < now() - 5s
       ORDER BY created_at LIMIT 100
       FOR UPDATE SKIP LOCKED
    2. 对每行 settle_one (见 §worker)
    3. 异常: retry_count++, 留 status='pending', 下次再试
       retry_count > 3 → status='dead'
```

## 数据库变更

### 新表 `pending_billing`

```sql
CREATE TABLE pending_billing (
  id UUID PRIMARY KEY,
  request_id UUID UNIQUE NOT NULL,
  user_id INT NOT NULL REFERENCES users(id),
  api_key_id INT NOT NULL REFERENCES api_keys(id),
  model_id INT NOT NULL REFERENCES models(id),
  channel_id INT NOT NULL REFERENCES channel_configs(id),
  provider_id INT NOT NULL REFERENCES providers(id),
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  cache_read_tokens INT NOT NULL DEFAULT 0,
  cache_creation_tokens INT NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | settled | dead
  retry_count INT NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_at TIMESTAMPTZ
);
CREATE INDEX ix_pending_billing_status_created
  ON pending_billing(status, created_at)
  WHERE status = 'pending';
```

### `usage_records` 加列

```sql
ALTER TABLE usage_records
  ADD COLUMN channel_id INT REFERENCES channel_configs(id);
CREATE INDEX ix_usage_records_channel_id ON usage_records(channel_id);
```

老记录 `channel_id` 允许为 NULL，前端按"无渠道"降级。

### ORM 文件

| 文件 | 变更 |
|------|------|
| `backend/app/models/pending_billing.py` | 新增 `PendingBilling` 模型 |
| `backend/app/models/usage.py` | `UsageRecord` 加 `channel_id: Mapped[int \| None]` |
| `backend/alembic/versions/xxxx_add_pending_billing.py` | 新增：建表 + 加列 + 索引 |

## 后端实现

### 新模块 `backend/app/services/billing/`

```
billing/
├── __init__.py
├── compute.py     # compute_cost (从 billing_service.py 搬过来, 加 cache_creation, 修 multiplier)
├── pending.py     # write_pending_billing, claim_pending_batch
├── settle.py      # settle_one
└── worker.py      # BillingWorker class
```

### `compute.py`

```python
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
    """返回 cents (向上取整). 调用方负责把 cache_creation_price 设为 input_price."""
    base = (
        input_tokens / 1000 * input_price_micro_yuan
        + output_tokens / 1000 * output_price_micro_yuan
        + cache_read_tokens / 1000 * cache_read_price_micro_yuan
        + cache_creation_tokens / 1000 * cache_creation_price_micro_yuan
    )
    return math.ceil(base * channel_multiplier / 10_000)


def compute_costs_for_pending(pending: PendingBilling, db: AsyncSession) -> int:
    """settle_one 调用: 加载 channel + model 实际价格, 调 compute_cost."""
    channel = await db.scalar(select(ChannelConfig).where(ChannelConfig.id == pending.channel_id))
    model = await db.scalar(select(Model).where(Model.id == pending.model_id))
    return compute_cost(
        input_tokens=pending.input_tokens,
        output_tokens=pending.output_tokens,
        cache_read_tokens=pending.cache_read_tokens,
        cache_creation_tokens=pending.cache_creation_tokens,
        input_price_micro_yuan=model.input_price,
        output_price_micro_yuan=model.output_price,
        cache_read_price_micro_yuan=model.cache_read_price,
        cache_creation_price_micro_yuan=model.input_price,  # 行业惯例
        channel_multiplier=channel.multiplier,
    )
```

### `pending.py`

```python
async def write_pending_billing(
    db, *, request_id: UUID, user_id: int, api_key_id: int,
    model_id: int, channel_id: int, provider_id: int,
    input_tokens: int, output_tokens: int,
    cache_read_tokens: int, cache_creation_tokens: int,
) -> PendingBilling: ...

async def claim_pending_batch(
    db, *, max_age_seconds: int = 5, limit: int = 100,
) -> list[PendingBilling]:
    """FOR UPDATE SKIP LOCKED; 显式释放锁靠事务结束"""
```

### `settle.py`

```python
async def settle_one(db, pending: PendingBilling) -> None:
    """
    1. SELECT channel_configs.multiplier, models.{input,output,cache_read}_price
    2. cost = compute_cost(..., channel_multiplier=channel.multiplier)
    3. SELECT user ... FOR UPDATE
    4. user.balance -= cost
    5. INSERT request_logs (channel_id, status='success', cost_cents=cost)
    6. INSERT billing_records (request_log_id, amount=cost, balance_after)
    7. INSERT usage_records (channel_id, cost_cents=cost, ...)
    8. UPDATE pending_billing SET status='settled', settled_at=now()
    9. COMMIT
    on any exception: ROLLBACK, 留 status='pending' 给下次扫
    """
```

### `worker.py`

```python
class BillingWorker:
    def __init__(self, session_factory, *,
                 scan_interval: int = 30,
                 max_age_seconds: int = 5,
                 max_retry: int = 3,
                 batch_limit: int = 100): ...
    async def start(self) -> None: ...   # 在 lifespan 内启动
    async def stop(self) -> None: ...    # cancel + wait
    async def _run_loop(self) -> None: ...
    async def _scan_and_settle(self) -> int: ...
```

启动位置：`backend/api/app.py` 的 `lifespan` 异步上下文管理器内，session_factory 初始化之后。

## proxy.py 改动

| 位置 | 改动 |
|------|------|
| 常量 `MIN_BALANCE_THRESHOLD_CENTS` | `100` → `10` |
| 第 6 步（pre-reserve） | **删除整段**：`estimated_cost` 计算、`with_for_update` 锁、`user.balance = ...`、`db.flush() + db.commit()` |
| `_settle_billing` 函数 | **整段删除** |
| `billing_stream` finally 块 | 改为：调 `pending.write_pending_billing(...)` 然后 commit |
| `MAX_COST_CENTS` 常量 | 删除（不再用） |

新 `billing_stream` 关键改动：
```python
async def billing_stream():
    nonlocal accumulated_usage
    try:
        async for chunk in provider_instance.stream_response(provider_body, request_id=...):
            usage = _extract_usage_from_sse_line(chunk)
            if usage:
                for k in (...,):  # 累计 4 个 token
                    val = usage.get(k, 0)
                    if val: accumulated_usage[k] = val
            yield chunk
    finally:
        try:
            await pending.write_pending_billing(
                db, request_id=uuid.uuid4(),
                user_id=user.id, api_key_id=api_key.id,
                model_id=model.id,
                channel_id=routed.db_channel_id,  # ← multiplier 终于派上用场
                provider_id=provider.id,
                input_tokens=accumulated_usage["input_tokens"] or 0,  # 取消 or 100
                output_tokens=accumulated_usage["output_tokens"] or 0,
                cache_read_tokens=accumulated_usage["cache_read_tokens"] or 0,
                cache_creation_tokens=accumulated_usage["cache_creation_tokens"] or 0,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Failed to write pending_billing; user may be undercharged")
            # 不抛 - 用户响应已发出
```

注意：`input_tokens or 0`（不是 `or 100`）—— 既然没预扣，0 input 应当如实记录为 0。

## API/前端

### 后端

`backend/app/schemas/usage.py` → `UsageRecordResponse` 加 `channel_id: int | None`。
`backend/app/routers/usage.py` → `/api/usage/history` 返回时 LEFT JOIN `channel_configs` 拿 `channel_name`，新增 `channelName` 字段。

### 前端

| 文件 | 变更 |
|------|------|
| `frontend/lib/api/usage.ts` | `UsageRecord` 加 `channelId`, `channelName?` |
| `frontend/app/(user)/usage/page.tsx` | 表格新增"渠道"列 |

## 错误处理清单

| 场景 | 处理 |
|------|------|
| pre-flight 失败 (balance < 10) | 402，用户充值 |
| upstream 401/403/5xx | 不写 pending，不扣钱 |
| pending 写入失败 | 用户已收到响应；logger.exception + 暂存 in-memory 待手工补；**接受偶尔丢钱风险**（概率 < 0.01%） |
| worker 扫到 pending 处理失败 | retry_count++，留 status='pending' |
| worker 失败 > 3 次 | status='dead'，需 SQL 查 + 人工补扣 |
| 用户余额在流中途被花光 | 流照样完成，pending 正常写，worker 扣到负数（接受） |

## 一次性补钱

部署后执行：
```sql
UPDATE users SET balance = balance + 59873 WHERE id = 1;
```

不写 billing_records（`request_log_id` 有 UNIQUE NOT NULL 约束，补偿无对应请求）。财务对账时单独说明。

## 测试

### 单元测试 `backend/tests/services/billing/`

- `test_compute.py`:
  - multiplier 0.5 → cost = 50% 基线
  - cache_creation 按 input_price 收
  - 5-10 条历史 usage_records 回放，cost 在 1% 内
- `test_settle.py`:
  - 成功路径：balance 扣减 + 三表写入 + status='settled'
  - 失败路径：retry_count++, 留 status='pending'
  - 第 3 次失败转 'dead'
- `test_worker.py`:
  - `_scan_and_settle` 处理注入的 pending
  - 启动/停止生命周期

### 集成测试 `backend/tests/integration/test_billing_flow.py`

- 完整流：API → 流成功 → pending → worker → balance 扣减
- 流失败：API → upstream 5xx → 不写 pending → balance 不变
- 余额耗尽：balance=10 cents（pre-flight 门槛）能完成调用；worker 扣完后余额变负数
- 并发：N 并发调用 + SKIP LOCKED 串行化
- 回归：旧 usage_records 查询不带 channel_id 不报错

## 部署顺序

1. **alembic 迁移**（加 pending_billing 表、usage_records.channel_id 列）
2. **部署新代码**（proxy.py 改写、worker 启动）
3. 跑 1-2 天稳定后**删旧 `_settle_billing` 和 MAX_COST_CENTS**
4. 跑一次性补钱 SQL
5. 老 usage_records.channel_id 为 NULL，前端"无渠道"降级

## 涉及文件

### 后端
- `backend/app/routers/proxy.py` (改)
- `backend/app/services/billing_service.py` (旧 compute_cost 搬到 compute.py)
- `backend/app/services/billing/{compute,pending,settle,worker}.py` (新)
- `backend/app/models/pending_billing.py` (新)
- `backend/app/models/usage.py` (改)
- `backend/app/schemas/usage.py` (改)
- `backend/app/routers/usage.py` (改)
- `backend/api/app.py` (lifespan 启动 worker)
- `backend/alembic/versions/xxxx_add_pending_billing.py` (新)

### 前端
- `frontend/lib/api/usage.ts` (改)
- `frontend/app/(user)/usage/page.tsx` (改)

### 删除
- `proxy.py` 中 `_settle_billing` 整段
- `proxy.py` 中 `MAX_COST_CENTS` 常量
- `proxy.py` 中 pre-reserve 的 6 步逻辑

## 风险

| 风险 | 缓解 |
|------|------|
| pending 写入失败导致丢钱 | 概率 < 0.01%；日志 + request_logs(status='billing_lost') 兜底 |
| worker 自身崩 | 进程内 task，崩了进程也崩；lifespan 重启时再起。SKIP LOCKED 保证不双扣 |
| 用户余额被 worker 扣到负数 | 接受。下一调用 pre-flight 拒绝 |
| `cache_creation` 之前漏算 → 现加收 → 用户被加费 | 历史余额不变（只看 usage_records），新计费从新调用起算 |
| `channel_id` 老数据 NULL | 前端降级显示 |

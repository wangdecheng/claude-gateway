# Backend: Proxy & Billing System

## 涉及文件

| 职责 | 文件 |
|------|------|
| 代理路由入口 | `backend/app/routers/proxy.py` |
| 计费计算 | `backend/app/services/billing/compute.py` |
| Pending 队列写入/认领 | `backend/app/services/billing/pending.py` |
| 结算（扣余额+写审计表） | `backend/app/services/billing/settle.py` |
| 异步结算 Worker | `backend/app/services/billing/worker.py` |
| 折扣系数应用 | `backend/app/services/billing/token_coefficient.py` |
| SSE 流式改写（模型名/系数） | `backend/app/services/streaming/sse_rewrite.py` |
| 模型路由解析 | `backend/api/model_router.py` |
| Provider 加密密钥池 | `backend/app/services/provider_service.py` |
| API Key 验证 | `backend/api/dependencies.py` -> `require_api_key` |
| ORM 模型 | `pending_billing.py`, `request_log.py`, `billing_record.py`, `usage.py` |
| Request schema | `backend/app/schemas/proxy.py` |
| ⚠️ 遗留 | `backend/app/services/billing_service.py` (LEGACY - 同步计费，引用已退役的 `ChannelConfig`，**勿用**) |

> 计费已从「同步预扣+流内结算」改为「**异步 pending + 后台 worker 结算**」。`billing_service.py` 是旧路径的残留，仅在 DB 未迁移的旧环境里可能被引用；新代码一律走 `services/billing/` 包。

## POST /v1/messages 全链路

### 请求阶段（同步，`proxy.py::create_message`）

```
1. 鉴权
   require_api_key(request)
     -> 提取 Authorization: Bearer sk-<hex>
     -> 按 key_prefix 查 api_keys 表
     -> bcrypt 验证完整 key hash
     -> 校验 User.status == "active"
     -> 返回 (User, ApiKey)

2. 模型解析
   ModelRouter(settings, db)
     -> 若 api_key.channel_id 存在: resolve_with_channel(model, channel_id)
        （在指定 provider 子集内解析）
     -> 否则: resolve_from_db(model)
     -> ResolvedModel(db_model_id, db_provider_id, db_route_id,
                      provider_model, provider_id, ...)
     -> db_model_id 为 None 时抛 UNSUPPORTED_MODEL

3. 定价 + 折扣
   _lookup_model(db, body.model) -> Model (input_price, output_price)
   TokenCoefficientService.get_for_model(model.id) -> coefficient (折扣)

4. Provider
   SELECT Provider WHERE id = routed.db_provider_id  (status == "active")
   -> channel_name, multiplier, api_base_url, adapter

5. 密钥池
   _get_active_upstream_key(db, provider_id, channel_id=provider.id)
     -> 若有 channel_keys 绑定: 联表取该 channel 的密钥子集
     -> 否则: 该 provider 所有 active ProviderKey
     -> 取第一把 (keys[0])，AES-256-GCM 解密 (provider_id 作 AAD)

6. 余额预检（仅门槛，不预扣）
   user.balance >= 10  (最小余额 ¥0.10 / 10 分)
   不足抛 402 INSUFFICIENT_BALANCE

7. Provider 实例
   registry.get(provider_id, api_key=upstream_key, base_url=...)
     -> 按 (provider_id, sha256(api_key)[:16]) 缓存
     -> DeepSeekProvider / GlmProvider / MiniMaxProvider / VolcengineProvider

8. 释放请求事务
   db.commit()  <-- 在开流式前释放请求级事务
                  finally 会用新事务写 pending

9. 提交下游 HTTP 200 前打开上游流并读取首个 chunk
   -> 上游错误响应: 保留状态码、原始 body 与允许的重试/追踪头后直接返回
   -> 上游 401/403: 转换为网关 502（Provider 凭据故障）
   -> 建连/协议错误: 502；等待响应超时: 504
   -> 网关不重试，由下游客户端决定是否重试
```

### 流式阶段（`billing_stream` 生成器）

```
10. provider_instance.stream_response(body, request_id=...)
     -> httpx 异步流 -> Anthropic SSE 事件
     对每个 chunk:
       a. 解析 usage (message_start / message_delta):
          input / output / cache_read / cache_creation (last-wins 累积)
       b. 抓取 message_start.message.id -> upstream_message_id
          (用于交叉比对 Claude Code JSONL 会话与上游日志)
       c. 在 SSE chunk 上就地改写:
          - provider_model -> 原始 Claude 模型名 (如 astron-code-latest -> claude-...)
          - 应用 token 系数 (折扣) 到 usage 字段
          - 上游 SSE error 事件跳过所有改写，原样转发
       d. yield chunk 给客户端

   流中传输故障直接中断，不补写错误文本、end_turn 或 message_stop。

11. finally (独立事务)
    adjusted = apply_coefficient(accumulated_usage, coefficient)
    write_pending_billing(
        request_id=uuid4(),   # UNIQUE
        user_id, api_key_id, model_id, route_id, provider_id,
        input/output/cache_read/cache_creation tokens,
        upstream_message_id,
    )
    db.commit()
    失败: rollback + 记日志 (不影响已返回的流)

   正常完成时按现有规则写入；错误流仅在上游已明确报告 usage 时写入，
   无 usage 的失败请求不创建 pending_billing。
```

### 结算阶段（`BillingWorker`，进程内 asyncio task，每 30s 扫描）

```
12. 认领批次 (短事务)
    claim_pending_batch(max_age_seconds=5, limit=100)
      SELECT ... FOR UPDATE SKIP LOCKED
      WHERE status='pending' AND created_at < now()-5s
      -> 只认领创建超过 5s 的行，避免抢到还在 finally 写入中的行
      ORDER BY created_at LIMIT 100
    commit  (释放行锁)

13. 逐行结算 (每行独立短事务)
    settle_one(db, pending):
      cost = compute_costs_for_pending(pending, db)
      SELECT user FOR UPDATE          # 行级锁防并发扣减
      user.balance -= cost
      INSERT request_log  (request_id = pending.request_id.hex)
      INSERT billing_record (request_log_id UNIQUE, amount, balance_after)
      INSERT usage_record  (denormalized model = public_name)
      pending.status = 'settled'; pending.settled_at = now
    commit

14. 失败处理
    mark_retry(): retry_count++, last_error = exc
    超过 max_retry (3) -> status='dead' (死信，人工介入)
```

## 计费模型

### 价格单位
- **DB 存储**: 微厘/千 token (micro-yuan per 1K)
  - 例如 `input_price = 1_000` 表示 ¥0.001 / 1K input tokens
- **最终扣款**: 分 (cent/fen), `1 分 = 10_000 微厘`

### Channel 倍率
每个 `Provider` 有一个 `multiplier`:
- 原生渠道: 1.0 (默认)
- 跨供应商渠道: 1.2 ~ 1.5

### compute_cost 公式 (`billing/compute.py`)

```python
effective_input = input_tokens + cache_creation_tokens + cache_read_tokens / 10
base_micro_yuan = (effective_input / 1000 * input_price
                 + output_tokens / 1000 * output_price)
cost_cents = ceil(base_micro_yuan * channel_multiplier / 10_000)
```

- **cache_creation 按 input 全价**计费
- **cache_read 按 input 的 1/10** 计费 (10% / 1折)
- 结果向上取整 (`math.ceil`)，最小 0

> ⚠️ 旧文档里 `cache_read_price` 单独列字段 + `base = input + output + cache_read×price` 的公式已**过时**。实际 `compute.py` 不使用独立 cache_read 价格列，而是把 cache_read 折算成 1/10 input。

## 防重复扣款

两层 UNIQUE 兜底：
- `pending_billings.request_id` UNIQUE — 同一 request 重复写 pending 会抛 IntegrityError
- `billing_records.request_log_id` UNIQUE — 同一 request_log 重复结算会 INSERT 失败

加上 `pending_billings.status` (pending/settled/dead) 状态机保证幂等。

## 余额安全

- **不再预扣**：请求路径只做 ¥0.10 门槛检查，不锁余额、不扣估计值
- `SELECT user FOR UPDATE` 行级锁仅在 **worker 结算** 时发生，串行化扣减
- 结算失败自动重试 3 次，超限转 `dead` 不丢账（pending 行仍在，可人工处理）
- 多 worker / 多实例安全：`FOR UPDATE SKIP LOCKED` 各自认领不相交批次
- `pending_billings` 既是结算队列也是审计证据：流式已返回但未结算的请求都留痕

## 常见开发场景

### 新增计费维度 / 改定价公式
1. `billing/compute.py::compute_cost` — 改公式
2. `app/models/model.py` — 若新字段落 DB，加列
3. `alembic/` — 生成迁移
4. `billing/settle.py::settle_one` — 若影响审计表写入，同步更新

### 修改结算 / 重试逻辑
1. `billing/settle.py` — `settle_one` / `mark_retry` / `max_retry_reached`
2. `billing/worker.py` — 扫描间隔、批次大小、重试上限

### 修改流式阶段的 usage 抓取 / 改写
1. `proxy.py::billing_stream` — `_extract_usage_from_sse_line`、`_apply_coefficient_to_sse_event`
2. `streaming/sse_rewrite.py` — SSE 事件改写规则

### 新增计费端点
参照 `proxy.py` 模式：鉴权 -> 解析 -> 预检(¥0.10) -> 流式 -> `finally` 写 `pending_billings`。
结算由共享的 `BillingWorker` 自动处理，新端点无需关心结算。

# Backend: Proxy & Billing System

## 涉及文件

| 职责 | 文件 |
|------|------|
| 代理路由入口 | `backend/app/routers/proxy.py` |
| 计费计算 | `backend/app/services/billing_service.py` |
| 上游请求转发 | `backend/app/services/upstream_client.py` (deprecated, now uses providers/) |
| 模型路由解析 | `backend/api/model_router.py` |
| Provider 加密密钥池 | `backend/app/services/provider_service.py` |
| API Key 验证 | `backend/api/dependencies.py` → `require_api_key` |
| ORM 模型 | `backend/app/models/request_log.py`, `backend/app/models/billing_record.py` |
| Request schema | `backend/app/schemas/proxy.py` |

## POST /v1/messages 全链路

```
1. 鉴权
   require_api_key(request)
     → 提取 Authorization: Bearer sk-<hex>
     → 按 key_prefix (前10位) 查 api_keys 表
     → bcrypt 验证完整 key hash
     → 校验 User.status == "active"
     → 返回 (User, ApiKey)

2. 模型解析
   ModelRouter.resolve_from_db(model_name)
     → Model.public_name 匹配 (status == "active")
     → 获取关联 Provider (status == "active")
     → 获取关联 ChannelConfig (model_id, status == "active")
     → 返回 (model_id, model_public_name, provider_id, provider_name,
              channel_id, multiplier, adapter, base_url)

3. 密钥池
   get_active_upstream_key(db, provider_id, channel_id)
     → 如果 channel_id 存在: 通过 channel_keys 联表限定的密钥池
     → 如果 channel_id 不存在: 该 provider 所有 active 密钥
     → 随机选择一个 (负载均衡)
     → 解密密钥: AES-256-GCM, provider_id 作 AAD

4. 余额预检
   user.balance >= 100 (最小余额 1 元/100 分)

5. 费用预扣
   BEGIN
   SELECT user FOR UPDATE (行级锁防并发)
   预估费用 = max_tokens × output_price × channel.multiplier
   user.balance -= 预估费用
   COMMIT

6. 流式转发
   ProviderRegistry.get(provider_id, api_key, base_url)
     → DeepSeekProvider(AnthropicMessagesTransport)
   provider.stream_response(request_body)
     → httpx 异步流 → SSE 事件流 → yield (event, tokens_used)

7. 结算 (在 billing_stream 的 finally 中)
   compute_cost(input, output, cache_read, prices, multiplier)
     → 三段计费: input_tokens/1000 × input_price
                 + output_tokens/1000 × output_price
                 + cache_read_tokens/1000 × cache_read_price
     → × channel.multiplier
     → 微厘 → 分: ceil(total / 10_000)
   adjust_balance: balance += (reserved - actual)
   INSERT request_log (request_id UUID, user_id, model_id, ..., tokens, cost, status)
   INSERT billing_record (request_log_id UNIQUE, amount, balance_after)
```

## 计费模型

### 价格单位
- **DB 存储**: 微厘/千 token (micro-yuan per 1K)
  - 例如 `input_price = 1_000` 表示 ¥0.001 / 1K input tokens
- **最终扣款**: 分 (cent/fen), `1 分 = 10_000 微厘`

### Channel 倍率
每个 model-provider 组合 (ChannelConfig) 有一个 `multiplier`:
- 原生渠道: 1.0 (默认)
- 跨供应商渠道: 1.2 ~ 1.5

### compute_cost 公式
```python
base = (input/1000 * input_price
      + output/1000 * output_price
      + cache_read/1000 * cache_read_price)
total = base * channel_multiplier
cents = ceil(total / 10_000)
```

## 防重复扣款

- `billing_records.request_log_id` 有 UNIQUE 约束
- 如果重复结算同一个请求，INSERT 会失败
- `request_logs` 记录最终状态: success / usage_missing / error

## 余额安全

- `SELECT ... FOR UPDATE` 行级锁: 并发请求串行化余额扣减
- 最小余额门槛 (100 分): 防止零余额或负余额请求
- 预扣 > 实际结算 → 退还差额
- 预扣 < 实际结算 → 追加扣款 (仅在余额足够时)

## 常见开发场景

### 新增计费维度 (如按模型版本差异化定价)
1. `billing_service.py`: 修改 `compute_cost` 增加新维度
2. `models/model.py`: 如果新字段在 DB，添加列
3. `schemas/proxy.py`: 如需要，修改 request schema
4. `alembic/`: 生成迁移文件

### 修改结算逻辑
1. `proxy.py` → `billing_stream` 的 `finally` 块
2. `billing_service.py` → `compute_cost`, `process_token_recording`

### 新增 API 端点且需要计费
1. 参照 `proxy.py` 模式: 鉴权 → 解析 → 预检 → 预扣 → 执行 → 结算
2. 复用 `billing_service.py` 的记录函数

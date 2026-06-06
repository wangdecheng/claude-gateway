# 调用记录优化 — 设计文档

**日期**: 2026-06-06
**状态**: 设计中

## 目标

1. 时间显示增加 `hh:mm:ss`，全局 `formatDate` 变更为日期 + 时分秒
2. 调用记录 Token 用量拆分为 4 列：输入 / 缓存读 / 缓存创建 / 输出
3. 移除 `total_tokens` 列（无实际计费用途）

## 变更范围

### 后端 (5 文件)

| 文件 | 变更 |
|------|------|
| `backend/app/models/usage.py` | 模型：`request_tokens` → `input_tokens`，移除 `total_tokens`，新增 `cache_read_tokens`、`cache_creation_tokens` |
| `backend/app/services/usage_service.py` | `record_usage` 新增 `cache_read_tokens`、`cache_creation_tokens` 参数；`get_user_usage_stats` 聚合改为 sum(input+output+cache_read+cache_creation) |
| `backend/app/routers/proxy.py` | `accumulated_usage` 新增 `cache_creation_tokens`；`_settle_billing` 传递 cache 字段 |
| `backend/app/schemas/usage.py` | `UsageRecordResponse`：alias 改为 `inputTokens`/`outputTokens`，新增 `cacheReadTokens`/`cacheCreationTokens`，移除 `totalTokens` |
| `backend/alembic/` | 自动生成迁移：`request_tokens` → `input_tokens`，删除 `total_tokens`，新增 `cache_read_tokens`、`cache_creation_tokens` |

### 前端 (3 文件)

| 文件 | 变更 |
|------|------|
| `frontend/lib/utils/format.ts` | `formatDate` 由 `toLocaleDateString` 改为 `toLocaleString`，增加 `hour/minute/second/hour12:false` |
| `frontend/lib/api/usage.ts` | `UsageRecord` 接口：`requestTokens`→`inputTokens`，`responseTokens`→`outputTokens`，新增 `cacheReadTokens`、`cacheCreationTokens`，移除 `totalTokens` |
| `frontend/app/(user)/usage/page.tsx` | 表头改为 `时间 | 模型 | 输入 | 缓存读 | 缓存创建 | 输出 | 费用`，绑定新字段 |

### 影响分析

`formatDate` 全局变更影响 4 个页面：
- `frontend/app/(user)/usage/page.tsx` — 调用记录 & 每日用量
- `frontend/app/(user)/recharge/page.tsx` — 充值记录
- `frontend/components/data/KeyList.tsx` — API Key 列表
- `frontend/app/admin/users/page.tsx` — Admin 用户列表

## 设计决策

### 字段语义

上游 Anthropic Messages API 返回的 usage 对象：

| 字段 | 说明 | 映射 |
|------|------|------|
| `input_tokens` | 纯新输入（未命中缓存） | `input_tokens` |
| `cache_read_input_tokens` | 命中缓存的 token | `cache_read_tokens` |
| `cache_creation_input_tokens` | 写入缓存的 token（非 input 子集，可能 > input） | `cache_creation_tokens` |
| `output_tokens` | 模型生成的响应 token | `output_tokens` |

`cache_creation_input_tokens` 由 DeepSeek provider (`backend/providers/deepseek/client.py`) 中的 `_fill_deepseek_usage_cache_creation` 合成或提取，直接使用无需额外处理。

### 表头展示

```
时间 | 模型 | 输入 | 缓存读 | 缓存创建 | 输出 | 费用
```

### 每日统计

`get_user_usage_stats` 的 `tokens` 聚合改为：
```sql
SUM(input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens)
```

## 数据库迁移

```sql
-- 重命名
ALTER TABLE usage_records RENAME COLUMN request_tokens TO input_tokens;
ALTER TABLE usage_records RENAME COLUMN response_tokens TO output_tokens;
-- 删除
ALTER TABLE usage_records DROP COLUMN total_tokens;
-- 新增
ALTER TABLE usage_records ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE usage_records ADD COLUMN cache_creation_tokens INTEGER NOT NULL DEFAULT 0;
```

## 不涉及

- 每日用量图表不做调整（保持现有的调用次数 / Tokens / 费用三列）
- `compute_cost` 计费逻辑不变
- `DailyStat` 接口不变

# Backend: Database

## 涉及文件

| 职责 | 文件 |
|------|------|
| Base 声明 | `backend/app/database.py` |
| ORM 模型 | `backend/app/models/*.py` |
| Alembic 配置 | `backend/alembic/` (env.py, alembic.ini) |
| Migration 版本 | `backend/alembic/versions/*.py` |
| 种子数据 | `backend/app/seed.py` |
| DB URL 配置 | `backend/config/settings.py` → `database_url` |
| App 启动建表 | `backend/api/app.py` → `lifespan` |

## 数据库连接

### 默认连接
```
postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api
```
配置在 `settings.DATABASE_URL`，可通过 `.env` 覆盖。

### 测试环境
```
sqlite+aiosqlite:///:memory:
```
测试文件在导入前设 `os.environ["DATABASE_URL"] = "..."`。

### 引擎创建
```python
# backend/app/database.py
if "sqlite" in database_url:
    engine = create_async_engine(database_url.replace("sqlite:///", "sqlite+aiosqlite:///"))
else:
    engine = create_async_engine(database_url)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

## 实体关系图

```
users ──1:N──> api_keys
users ──1:N──> usage_records
users ──1:N──> payment_records
users ──1:N──> request_logs
users ──1:N──> billing_records
users ──1:N──> redemption_usages

providers ──1:N──> provider_keys
providers ──1:N──> models
providers ──1:N──> channel_configs

models ──1:N──> channel_configs

channel_configs ──1:N──> channel_keys ──N:1──> provider_keys

api_keys ──1:N──> request_logs
models ──1:N──> request_logs
channel_configs ──1:N──> request_logs

request_logs ──1:1──> billing_records  (UNIQUE)

redemption_codes ──1:N──> redemption_usages
```

## Model 详情

### users
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| email | String(255) unique | 登录邮箱 |
| password_hash | String(255) | bcrypt |
| balance | Integer | 余额，单位 分 |
| role | String(20) | user / admin |
| status | String(20) | active / disabled |
| created_at, updated_at | DateTime | |

### api_keys
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| user_id | FK → users.id | |
| name | String(100) | 用户给 key 起的名字 |
| key_prefix | String(10) | sk- + 前 10 位 hex，用于快速查找 |
| key_hash | String(255) | bcrypt 完整 hash |
| status | String(20) | active / revoked |
| last_used_at | DateTime | |
| created_at | DateTime | |

### providers
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| name | String(100) unique | Anthropic, OpenAI, RightCodes |
| api_base_url | String(500) | 上游 API 地址 |
| auth_header | String(100) | Authorization / x-api-key |
| adapter | String(50) | openai-chat-completions / anthropic-messages |
| status | String(20) | active / disabled |

### provider_keys
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| provider_id | FK → providers.id | |
| key_encrypted | Text | AES-256-GCM + base64 |
| key_prefix | String(20) | 脱敏展示: sk-****xxxx |
| status | String(20) | active / revoked |

### models
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| public_name | String(100) | 对外名称: claude-opus-4-8 |
| provider_id | FK → providers.id | 默认 provider |
| provider_model_id | String(100) | 上游模型 ID |
| description | Text | |
| input_price | Integer | 微厘/千 token |
| output_price | Integer | 微厘/千 token |
| cache_read_price | Integer | 缓存读取价格 |
| status | String(20) | active / disabled |

### channel_configs
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| model_id | FK → models.id | |
| provider_id | FK → providers.id | |
| multiplier | Float | 价格倍率 |
| is_default | Boolean | 是否默认渠道 |
| status | String(20) | active / disabled |

### channel_keys
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| channel_id | FK → channel_configs.id | |
| provider_key_id | FK → provider_keys.id | |
| UNIQUE(channel_id, provider_key_id) | | |

### request_logs
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| request_id | UUID unique | 每请求唯一 ID |
| user_id | FK | |
| api_key_id | FK | |
| model_id | FK | |
| channel_id | FK | |
| provider_id | FK | |
| input_tokens | Integer | |
| output_tokens | Integer | |
| cache_read_tokens | Integer | |
| cost_cents | Integer | 实际扣费(分) |
| latency_ms | Integer | |
| status | String(50) | success / usage_missing / error |

### billing_records
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| request_log_id | FK UNIQUE | 1:1，防重复扣款 |
| user_id | FK | |
| amount_cents | Integer | |
| balance_after_cents | Integer | |
| created_at | DateTime | |

### payment_records
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| user_id | FK | |
| amount | Integer | 充值金额 (分) CHECK > 0 |
| method | String(20) | alipay / wechat |
| status | String(20) | pending / success / failed / cancelled |
| transaction_id | String unique | 幂等性保证 |
| created_at, updated_at | DateTime | |

### redemption_codes
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| code_hash | String(255) | bcrypt |
| code_prefix | String(10) | 用于快速查找 |
| amount | Integer | 面额 (分) CHECK > 0 |
| status | String(20) | issued / used / expired |
| expires_at | DateTime | |
| created_at | DateTime | |

### redemption_usages
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (PK) | |
| user_id | FK | |
| code_id | FK | |
| amount_cents | Integer | |
| used_at | DateTime | |

## 迁移 (Alembic)

### 生成新迁移
```bash
cd backend
uv run alembic revision --autogenerate -m "描述"
```

### 执行迁移
```bash
uv run alembic upgrade head
```

### 注意
- 应用启动时 `Base.metadata.create_all` 会自动建表 (dev 便利)
- 生产环境使用 Alembic 管理 schema 变更
- 迁移文件在 `backend/alembic/versions/` (前缀编号命名)
- `env.py` 从 `app.models import *` 确保所有模型被加载

## 种子数据

`app/seed.py` → `seed_dev_data(db)`:
- 3 个 Providers: Anthropic, OpenAI, RightCodes
- 5 个 Models: claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5, gpt-4o, gpt-4o-mini
- 8 个 ChannelConfigs (原生 + 跨供应商渠道)
- 幂等: 如果 Provider 表已有数据则跳过

## ⚠️ 关键约束

| 约束 | 表.列 | 目的 |
|------|--------|------|
| UNIQUE | billing_records.request_log_id | 防重复扣款 |
| UNIQUE | payment_records.transaction_id | 支付回调幂等 |
| UNIQUE | channel_keys(channel_id, provider_key_id) | 防重复绑定 |
| CHECK > 0 | payment_records.amount | 充值金额必须正数 |
| CHECK > 0 | redemption_codes.amount | 兑换码面额必须正数 |
| FOR UPDATE | 各种余额操作 | 并发安全 |

## 常见开发场景

### 新增表/列
1. 修改 `app/models/*.py` 中的 ORM 模型
2. `cd backend && uv run alembic revision --autogenerate -m "描述"`
3. 检查生成的迁移文件
4. `uv run alembic upgrade head`

### 修改种子数据
1. 编辑 `app/seed.py` 中的 `SEED_PROVIDERS`, `SEED_MODELS`, `SEED_CHANNEL_CONFIGS`
2. 重启应用或 `uv run python -m app.seed`

### 数据迁移脚本
1. 在 `alembic/versions/` 创建新的迁移文件
2. 在 `upgrade()` 中写迁移逻辑，`downgrade()` 中写回滚逻辑

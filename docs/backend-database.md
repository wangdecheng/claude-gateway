# Backend: Database

## 涉及文件

| 职责 | 文件 |
|------|------|
| Base 声明 | `backend/app/database.py` |
| ORM 模型 | `backend/app/models/*.py` |
| Alembic 配置 | `backend/alembic/` (env.py, alembic.ini) |
| Migration 版本 | `backend/alembic/versions/*.py` |
| 种子数据 | `backend/app/seed.py` |
| DB URL 配置 | `backend/config/settings.py` -> `database_url` |
| App 启动建表 | `backend/api/app.py` -> `lifespan` |

## 数据库连接

### 默认连接
```
postgresql+asyncpg://high_api:high_api_dev@localhost:5432/high_api
```
配置在 `settings.database_url`，可通过 `.env` 覆盖。

### 测试环境
```
sqlite+aiosqlite:///:memory:
```
测试文件在导入前设 `os.environ["DATABASE_URL"] = "..."`。SQLite 无需 PostgreSQL。

### 引擎创建 (`app/database.py`)
```python
if "sqlite" in database_url:
    engine = create_async_engine(database_url.replace("sqlite:///", "sqlite+aiosqlite:///"))
else:
    engine = create_async_engine(database_url)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

> ⚠️ 主键类型：**所有业务表 PK 都是 `Integer` 自增**，不是 UUID。仅 `pending_billings.id` / `pending_billings.request_id` 用 UUID（见下表）。

## 实体关系图

```
users ──1:N──> api_keys ──channel_id──> providers (nullable, NULL=legacy auto)
users ──1:N──> usage_records
users ──1:N──> payment_records
users ──1:N──> request_logs
users ──1:N──> billing_records
users ──1:N──> pending_billings        (异步计费队列)
users ──1:N──> redemption_usages
users ──1:N──> redemption_codes       (created_by, admin)

models ──1:N──> model_providers ──N:1──> providers
                 (provider_model, is_default, status)

providers ──1:N──> provider_keys
providers ──1:N──> model_providers
providers ──1:N──> channel_keys ──N:1──> provider_keys
                 (channel_keys: 把某 provider 的一把 provider_key 标记为"渠道专用"子集)

api_keys        ──1:N──> request_logs   (sk_id)
models          ──1:N──> request_logs
model_providers ──1:N──> request_logs    (route_id)
providers       ──1:N──> request_logs

pending_billings ──结算──> request_logs  (1:1 by request_id)
                            + billing_records (1:1, request_log_id UNIQUE)
                            + usage_records

token_coefficient_configs: scope=global (model_id NULL) | scope=model (model_id FK, CASCADE)
```

> 命名澄清：旧的 `channel_configs` 表已**不存在**，被 `model_providers`（`ModelProviderRoute`）取代。前端 `/api/admin/channels` 操作的就是 `model_providers`，命名保留仅为向后兼容。`Provider.channel_name` + `Provider.multiplier` 承载旧的渠道级展示/定价。

## Model 详情

> PK 列在每张表都是 `id Integer PK autoincrement`（除 `pending_billings` 用 UUID）。下表省略 PK 行。

### users
| 列 | 类型 | 说明 |
|----|------|------|
| email | String(255) unique, indexed | 登录邮箱 |
| password_hash | String(255) | bcrypt |
| balance | Integer | 余额，单位 分 |
| role | String(20) default "user" | user / admin |
| status | String(20) default "active" | active / disabled |
| created_at | DateTime | (无 updated_at) |

### api_keys
| 列 | 类型 | 说明 |
|----|------|------|
| user_id | FK -> users.id, indexed | |
| name | String(100) | 用户给 key 起的名字 |
| key_prefix | String(10) | sk- + 前 8 位 hex，用于快速查找 |
| key_hash | String(255) | bcrypt 完整 hash |
| status | String(20) default "active" | active / revoked |
| channel_id | FK -> providers.id, nullable, indexed | 绑定的 provider；NULL = 旧式自动路由 |
| last_used_at | DateTime, nullable | |
| created_at | DateTime | |

### providers
| 列 | 类型 | 说明 |
|----|------|------|
| name | String(100) | 渠道组名（与 channel_name 联合唯一） |
| channel_name | String(100) | 该 provider 的展示名 |
| multiplier | Float default 1.0 | 价格倍率（计费时应用） |
| api_base_url | String(500) | 上游 API 地址 |
| auth_header | String(50) default "Authorization" | Authorization / x-api-key |
| api_key_env | String(100) default "" | 持有上游 key 的环境变量名 |
| adapter | String(50) default "openai-chat-completions" | 协议适配器标识 |
| status | String(20) default "active" | active / inactive |
| created_at | DateTime | |
| UNIQUE(name, channel_name) | | 同名不同渠道可共存 |

### provider_keys
| 列 | 类型 | 说明 |
|----|------|------|
| provider_id | FK -> providers.id | |
| key_encrypted | Text | AES-256-GCM + base64 |
| key_prefix | String(20) | 脱敏展示: sk-****xxxx |
| status | String(20) default "active" | active / revoked（支持重新启用） |
| created_at | DateTime | |

> 加密：AES-256-GCM，`provider_id` 作 AAD（防跨 provider 复用），密文 base64 存 `key_encrypted`。

### models
| 列 | 类型 | 说明 |
|----|------|------|
| public_name | String(100) unique | 对外名称: claude-opus-4-8 |
| description | Text, nullable | |
| input_price | Integer | 微厘/千 token |
| output_price | Integer | 微厘/千 token |
| cache_read_price | Integer default 0 | 缓存读取价格（列存在；但 `compute.py` 实际按 input 的 1/10 计费，未使用此列） |
| status | String(20) default "active" | |
| created_at | DateTime | |

> ⚠️ 旧字段 `provider_id` / `provider_model_id` 已从 `models` **移除**（迁移 `dc16e024a564`）。模型↔上游的绑定现在在 `model_providers` 上。

### model_providers (ModelProviderRoute, 表名 `model_providers`)
| 列 | 类型 | 说明 |
|----|------|------|
| model_id | FK -> models.id | |
| provider_id | FK -> providers.id | |
| provider_model | String(200) | 上游真实模型 ID（如 glm-5.2、claude-opus-4-8-20250501） |
| is_default | Boolean default False | 是否该模型的默认渠道 |
| status | String(20) default "active" | active / inactive / deleted (soft-delete，保账单历史) |
| created_at | DateTime | |
| UNIQUE(model_id, provider_id) | | |

### channel_keys
| 列 | 类型 | 说明 |
|----|------|------|
| provider_id | FK -> providers.id | 绑定到的 provider（"渠道"） |
| provider_key_id | FK -> provider_keys.id | 被标记为该渠道专用的密钥 |
| created_at | DateTime | |
| UNIQUE(provider_id, provider_key_id) | | |

### pending_billings (异步计费队列, UUID PK)
| 列 | 类型 | 说明 |
|----|------|------|
| id | UUID (CHAR 36) PK | |
| request_id | UUID unique, indexed | 幂等键，重复写抛 IntegrityError |
| user_id | FK -> users.id | |
| api_key_id | FK -> api_keys.id | |
| model_id | FK -> models.id | |
| route_id | FK -> model_providers.id | |
| provider_id | FK -> providers.id | |
| input_tokens / output_tokens | Integer | |
| cache_read_tokens / cache_creation_tokens | Integer | |
| upstream_message_id | String(64), nullable, indexed | Anthropic message.id，交叉比对 Claude Code JSONL |
| status | String(20) default "pending" | pending / settled / dead |
| retry_count | Integer default 0 | |
| last_error | Text, nullable | |
| created_at | DateTime | |
| settled_at | DateTime, nullable | |

### request_logs
| 列 | 类型 | 说明 |
|----|------|------|
| request_id | String(36) unique | 每请求唯一 ID (= pending.request_id.hex) |
| user_id | FK, indexed | |
| sk_id | FK -> api_keys.id, indexed | 注意列名是 `sk_id` 不是 `api_key_id` |
| model_id | FK -> models.id | |
| route_id | FK -> model_providers.id | |
| provider_id | FK -> providers.id | |
| input_tokens / output_tokens | Integer | (无 cache token 列，cache token 在 pending/usage 里) |
| upstream_message_id | String(64), nullable, indexed | |
| cost_cents | Integer | 实际扣费(分) |
| latency_ms | Integer, nullable | |
| status | String(20) default "success" | success / usage_missing / error |
| created_at | DateTime, indexed | |

### billing_records (append-only 扣款账本)
| 列 | 类型 | 说明 |
|----|------|------|
| request_log_id | FK -> request_logs.id, UNIQUE | 1:1，防重复扣款 |
| user_id | FK, indexed | |
| amount_cents | Integer | 本次扣款(分) |
| balance_after_cents | Integer | 扣款后余额快照(审计) |
| created_at | DateTime, indexed | |

### usage_records
| 列 | 类型 | 说明 |
|----|------|------|
| user_id | FK, indexed | |
| api_key_id | FK -> api_keys.id | |
| model | String(100) | denormalized = public_name |
| input_tokens / output_tokens | Integer | |
| cache_read_tokens / cache_creation_tokens | Integer | |
| cost_cents | Integer | 分 |
| route_id | FK -> model_providers.id, nullable, indexed | |
| upstream_message_id | String(64), nullable, indexed | |
| created_at | DateTime, indexed | |

### payment_records
| 列 | 类型 | 说明 |
|----|------|------|
| user_id | FK, indexed | |
| amount | Integer CHECK > 0 | 充值金额 (分) |
| method | String(10) | alipay / wechat |
| status | String(20) default "pending" | pending / success / failed / cancelled |
| transaction_id | String(255), unique, nullable | 幂等性保证 |
| created_at, updated_at | DateTime | |

### redemption_codes
| 列 | 类型 | 说明 |
|----|------|------|
| code_hash | String(255) | bcrypt |
| code_prefix | String(10), indexed | 用于快速查找 |
| amount | Integer CHECK > 0 | 面额 (分) |
| status | String(20) default "issued" | issued / used / expired |
| expires_at | DateTime | |
| created_by | FK -> users.id, nullable | 创建该码的 admin |
| created_at | DateTime | |

### redemption_usages
| 列 | 类型 | 说明 |
|----|------|------|
| user_id | FK, indexed | |
| code_id | FK -> redemption_codes.id | |
| amount | Integer | 兑换金额 (分) |
| created_at | DateTime | |

### token_coefficient_configs (折扣系数, 全局+per-model)
| 列 | 类型 | 说明 |
|----|------|------|
| scope_type | String(10) | global / model |
| model_id | FK -> models.id, nullable, CASCADE | scope=model 时必填；scope=global 时必空 |
| coefficient | Float CHECK (0, 1] | 折扣系数 |
| updated_by | FK -> users.id, nullable | |
| updated_at, created_at | DateTime | |
| UNIQUE(model_id) | | per-model 至多一条 |
| CHECK scope-model 一致性 | | global⇒model_id IS NULL; model⇒model_id IS NOT NULL |

> 系数作用于 input / cache_creation / output 三个字段；**cache_read 不打折**（透传上游原值）。启动时 `TokenCoefficientService` 加载全局默认 + per-model 覆盖。

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
- 应用启动时 `Base.metadata.create_all` 会自动建表 (dev 便利)；生产用 Alembic
- 迁移文件在 `backend/alembic/versions/`（编号前缀 + 部分 hash 命名）
- `env.py` 从 `app.models` 导入所有模型确保被加载

## 种子数据 (`app/seed.py`)

`seed_dev_data(db)` + `seed_admin_user(db)`，幂等（已有数据则跳过）：

- **4 个 Providers**: Anthropic、OpenAI、RightCodes、GLM（各带 channel_name + multiplier）
- **5 个 Models**: claude-opus-4-8、claude-sonnet-4-6、claude-haiku-4-5、gpt-4o、gpt-4o-mini
- **9 条 Routes** (model_providers): 3 条 Anthropic 原生 + 1 条 GLM 备用(claude-opus-4-8) + 2 条 OpenAI 原生 + 3 条 RightCodes 跨供应商
- **1 个默认 admin 用户** (`287187910@qq.com`)，仅当无 admin 时创建

> Volcengine / DeepSeek / MiniMax 已在 `config/provider_catalog.py` 注册（用于 provider registry 与 admin 下拉），但**不在 seed 中自动建行**；需要通过 admin UI 或 SQL 显式插入。
>
> 旧文档说"3 Providers / 8 ChannelConfigs"已过时；ChannelConfig 表本身已不存在。

## ⚠️ 关键约束

| 约束 | 表.列 | 目的 |
|------|--------|------|
| UNIQUE | pending_billings.request_id | 防重复入队 |
| UNIQUE | billing_records.request_log_id | 防重复扣款 |
| UNIQUE | payment_records.transaction_id | 支付回调幂等 |
| UNIQUE | model_providers(model_id, provider_id) | 同模型同 provider 仅一条路由 |
| UNIQUE | channel_keys(provider_id, provider_key_id) | 防重复绑定 |
| UNIQUE | token_coefficient_configs(model_id) | per-model 至多一条系数 |
| UNIQUE | providers(name, channel_name) | 同名不同渠道可共存 |
| CHECK > 0 | payment_records.amount | 充值金额正数 |
| CHECK > 0 | redemption_codes.amount | 兑换码面额正数 |
| CHECK (0,1] | token_coefficient_configs.coefficient | 系数范围 |
| FOR UPDATE | user.balance（worker 结算时）+ pending_batch 认领 (`SKIP LOCKED`) | 并发安全 |

## 常见开发场景

### 新增表/列
1. 修改 `app/models/*.py` 中的 ORM 模型
2. `cd backend && uv run alembic revision --autogenerate -m "描述"`
3. 检查生成的迁移文件（autogenerate 可能漏索引/约束，手动补）
4. `uv run alembic upgrade head`

### 修改种子数据
1. 编辑 `app/seed.py` 中的 `SEED_PROVIDERS`、`SEED_MODELS`、`SEED_ROUTES`
2. 重启应用（lifespan 检测空库自动 seed）或 `uv run python -m app.seed`

### 数据迁移脚本
1. 在 `alembic/versions/` 创建新迁移文件
2. `upgrade()` 写迁移逻辑，`downgrade()` 写回滚
3. 复杂迁移可参考 `backend/scripts/migrate_channel_config.py`（旧 channel_config -> model_providers 迁移）

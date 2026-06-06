# Backend: Provider Plugin System

## 涉及文件

| 职责 | 文件 |
|------|------|
| Provider 抽象基类 | `backend/providers/base.py` |
| Provider 注册中心 | `backend/providers/registry.py` |
| Anthropic Messages 传输层 | `backend/providers/animations_messages.py` |
| DeepSeek 适配器 | `backend/providers/deepseek/client.py` |
| DeepSeek 请求构建 | `backend/providers/deepseek/request.py` |
| 速率限制器 | `backend/providers/rate_limit.py` |
| 错误映射 | `backend/providers/error_mapping.py` |
| Provider 异常 | `backend/providers/exceptions.py` |
| 模型列表解析 | `backend/providers/model_listing.py` |
| Provider catalog | `backend/config/provider_catalog.py` |
| Provider 业务逻辑 | `backend/app/services/provider_service.py` |
| Provider ORM | `backend/app/models/provider.py` |

## 架构层次

```
┌─────────────────────────────────────────────┐
│            ProviderRegistry                 │
│  - 工厂注册: {provider_id → factory_fn}     │
│  - 实例缓存: key = provider_id + sha256(key)│
│  - build_provider_config()                  │
│  - create_provider()                        │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│           BaseProvider (ABC)                │
│  + stream_response(request) → SSE stream    │
│  + list_model_ids() → [str]                 │
│  + cleanup()                                │
│  # _build_request_body()                    │
│  # _request_headers()                       │
│  # _transform_stream_event()                │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│   AnthropicMessagesTransport(BaseProvider)  │
│  - SSE 流解析 (line-delimited + event-     │
│    grouped 两种格式)                         │
│  - /models 端点查询模型列表                 │
│  - 错误响应体日志                           │
│  - 响应式流关闭 (遇到错误时)                │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│         DeepSeekProvider                    │
│  base_url: api.deepseek.com/anthropic       │
│  auth: x-api-key header                     │
│  重写: _build_request_body (thinking params)│
│        _request_headers (x-api-key)         │
│        _transform_stream_event (usage)      │
│        _send_model_list_request (OpenAI fmt)│
└─────────────────────────────────────────────┘
```

## 核心接口

### BaseProvider (ABC)

```python
class BaseProvider(ABC):
    config: ProviderConfig  # api_key, base_url, rate_limit, timeouts, ...

    @abstractmethod
    async def stream_response(self, request_body: dict) -> AsyncIterator[SSEEvent]:
        """流式转发请求，yield SSE 事件"""
        ...

    @abstractmethod
    async def list_model_ids(self) -> list[str]:
        """返回该 provider 支持的模型 ID 列表"""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """释放资源（如关闭 httpx client）"""
        ...

    # === 可选重写 ===
    def _build_request_body(self, body: dict) -> dict:
        """转换请求体（OpenAI ↔ Anthropic 格式）"""
        ...

    def _request_headers(self) -> dict:
        """构建鉴权头（Authorization / x-api-key / ...）"""
        ...

    def _transform_stream_event(self, event: dict) -> dict:
        """转换流事件格式（如标准化 usage 字段）"""
        ...
```

### ProviderConfig
```python
class ProviderConfig(BaseModel):
    api_key: str
    base_url: str
    rate_limit: int          # 速率限制 (请求/窗口)
    rate_window: int         # 窗口大小 (秒)
    max_concurrency: int     # 最大并发数
    read_timeout: float
    write_timeout: float
    connect_timeout: float
    proxy: str | None
    log_raw_payloads: bool
    log_raw_sse_events: bool
```

### GlobalRateLimiter
三层速率控制 + 重试:
1. **proactive**: 严格滑动窗口 (stored in Redis-compatible memory store)
2. **reactive**: 收到 429/5xx 时 block
3. **concurrency**: asyncio.Semaphore 控制最大并发
4. **execute_with_retry**: 指数退避 + 抖动

## ProviderRegistry 工作流

```python
registry = ProviderRegistry(settings)
provider = await registry.get(
    provider_id="deepseek",
    api_key="sk-...",          # 上游 API key
    base_url="https://..."     # 可选覆盖
)
# registry 内部:
# 1. 构建复合缓存键: f"{provider_id}:{sha256(api_key)}"
# 2. 命中缓存 → 返回已有实例
# 3. 未命中 → 查 PROVIDER_FACTORIES → 调用工厂函数
# 4. 缓存实例
# 5. 返回 provider
```

## 速率限制

```python
# settings.py 默认值
PROVIDER_RATE_LIMIT = 40       # 40 请求/窗口
PROVIDER_RATE_WINDOW = 60      # 60 秒窗口
PROVIDER_MAX_CONCURRENCY = 5   # 最多 5 并发
```

`execute_with_retry` 的退避策略:
- 429 Rate Limited: 等待 Retry-After 或 1s × 指数退避
- 5xx Server Error: 1s × 指数退避 (最多 3 次重试)
- 连接错误: 0.5s × 指数退避 (最多 2 次重试)

## 新增 Provider 步骤

以添加 OpenAI 直连为例:

### 1. 创建适配器 `backend/providers/openai/client.py`
```python
class OpenAIProvider(BaseProvider):
    async def stream_response(self, request_body):
        # 调用 OpenAI /v1/chat/completions with stream=True
        ...

    async def list_model_ids(self):
        # GET /v1/models
        ...
```

### 2. 注册到 catalog `backend/config/provider_catalog.py`
```python
ProviderDescriptor(
    id="openai",
    name="OpenAI Direct",
    transport="openai-chat-completions",
    base_url="https://api.openai.com",
    capabilities=[...],
)
```

### 3. 注册工厂 `backend/providers/registry.py`
```python
PROVIDER_FACTORIES = {
    "deepseek": lambda config: DeepSeekProvider(config),
    "openai": lambda config: OpenAIProvider(config),   # 新增
}
```

### 4. 添加 ORM 适配器类型（如需）
- `backend/app/models/provider.py`: 确认 `adapter` 字段支持 `"openai-chat-completions"`
- Seed 数据中插入 OpenAI provider

### 5. 前端 Admin 界面自动支持
- Provider adapter 下拉框 (admin/providers) 已支持 `openai-chat-completions` 和 `anthropic-messages` 两种类型

## 上游密钥安全

- 密钥通过 `provider_service.encrypt_api_key()` 加密存储
- 加密算法: AES-256-GCM
- AAD (附加认证数据): `provider_id` (防止密钥跨 provider 复用)
- 存储格式: base64(encrypted_key)
- 解密仅在 `get_active_upstream_key()` 调用时进行，用完即弃
- 前端 admin 界面支持添加/吊销 provider key

## 常见开发场景

### 适配新 AI 供应商
- 如上述 "新增 Provider 步骤"

### 修改速率限制策略
1. `providers/rate_limit.py`: 修改滑动窗口算法或重试策略
2. `config/settings.py`: 修改默认值 `PROVIDER_RATE_LIMIT` 等

### 修改流事件格式
1. 继承 `_transform_stream_event()` 处理特定事件
2. `providers/anthropic_messages.py`: 如果需要修改传输层行为

### Protocol 转换 (非 Anthropic → Anthropic)
1. 继承 `BaseProvider` (不用 `AnthropicMessagesTransport`)
2. 在 `_build_request_body()` 实现请求格式转换
3. 在 `_transform_stream_event()` 实现响应事件转换
4. 参照 `DeepSeekProvider` 的模式

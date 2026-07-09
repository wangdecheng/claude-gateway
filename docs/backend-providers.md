# Backend: Provider Plugin System

## 涉及文件

| 职责 | 文件 |
|------|------|
| Provider 抽象基类 | `backend/providers/base.py` |
| Provider 注册中心 | `backend/providers/registry.py` |
| Anthropic Messages 传输层 | `backend/providers/anthropic_messages.py` |
| DeepSeek 适配器 | `backend/providers/deepseek/client.py` |
| GLM 适配器 | `backend/providers/glm/client.py` |
| MiniMax 适配器 | `backend/providers/minimax/client.py` |
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
│  - PROVIDER_FACTORIES: {provider_id -> fn}   │
│  - 实例缓存: key = provider_id:sha256(key)[:16]
│  - build_provider_config() / create_provider()│
│  - get() 同步方法 (无 await)                  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│           BaseProvider (ABC)                │
│  + stream_response(request, *, request_id,  │
│      thinking_enabled) -> AsyncIterator[str] │
│  + preflight_stream(request)  (build 前校验) │
│  + list_model_ids() / list_model_infos()     │
│  + cleanup()                                │
│  # _build_request_body() / _request_headers()│
│  # _transform_stream_event(event, state, *)  │
│  # _new_stream_state(request, *, thinking)   │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│   AnthropicMessagesTransport(BaseProvider)  │
│  - 原生 Anthropic SSE 流解析                 │
│  - /v1/models 端点查询模型列表               │
│  - 错误响应体日志 / 响应式流关闭              │
└──────┬───────────────┬──────────────┬───────┘
       ▼               ▼              ▼
  DeepSeekProvider  GlmProvider   MiniMaxProvider
  api.deepseek.com  cn.morbuke.com  api.minimaxi.com
  /anthropic                         /anthropic
  (均走 Authorization Bearer，均 native Anthropic)
```

> 三家 provider 全部继承 `AnthropicMessagesTransport`（原生 Anthropic 兼容），差异在于：模型名回写、usage 合成、缓存 token 计算。

## 核心接口

### BaseProvider (ABC) (`providers/base.py`)

```python
class BaseProvider(ABC):
    def __init__(self, config: ProviderConfig): ...

    @abstractmethod
    async def stream_response(
        self,
        request: Any,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        thinking_enabled: bool | None = None,
    ) -> AsyncIterator[str]:
        """流式转发，yield Anthropic SSE 文本 chunk。"""

    def preflight_stream(self, request, *, thinking_enabled=None) -> None:
        """流式前 eager 构造上游请求，转换失败抛 InvalidRequestError。"""

    @abstractmethod
    async def list_model_ids(self) -> frozenset[str]: ...

    async def list_model_infos(self) -> frozenset[ProviderModelInfo]: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    # === 子类可重写的钩子 ===
    def _build_request_body(self, request, *, thinking_enabled=None) -> dict: ...
    def _request_headers(self) -> dict[str, str]: ...
    def _transform_stream_event(self, event, state, *, thinking_enabled) -> str | None: ...
    def _new_stream_state(self, request, *, thinking_enabled) -> Any: ...
    def _is_thinking_enabled(self, request, thinking_enabled=None) -> bool: ...
```

### ProviderConfig (`providers/base.py`)
```python
class ProviderConfig(BaseModel):
    api_key: str
    base_url: str | None = None
    rate_limit: int | None
    rate_window: int = 60
    max_concurrency: int = 5
    http_read_timeout: float = 300.0
    http_write_timeout: float = 10.0
    http_connect_timeout: float = ...
    enable_thinking: bool = True
    proxy: str = ""
    log_raw_sse_events: bool = False
    log_deepseek_usage: bool = False
    log_minimax_usage: bool = False
    log_glm_usage: bool = False
    log_api_error_tracebacks: bool = False
```

> ⚠️ 旧文档的 `read_timeout`/`write_timeout`/`connect_timeout`/`log_raw_payloads` 字段名已过时，实际前缀是 `http_`，并有 per-provider 的 usage 日志开关。

### GlobalRateLimiter (`providers/rate_limit.py`)
三层速率控制 + 重试:
1. **proactive**: 滑动窗口限流
2. **reactive**: 收到 429/5xx 时 block
3. **concurrency**: `asyncio.Semaphore` 控最大并发
4. **execute_with_retry**: 指数退避 + 抖动

## ProviderRegistry 工作流 (`providers/registry.py`)

```python
registry = ProviderRegistry(settings)          # app.state.provider_registry
provider = registry.get(                      # ⚠️ 同步方法，无需 await
    provider_id="glm",
    api_key="sk-...",      # 上游 API key (来自 DB 解密)
    base_url="https://..."  # 可选覆盖
)
# 内部:
# 1. 缓存键: f"{provider_id}:{sha256(api_key)[:16]}"  (取前 16 字符)
# 2. 命中 -> 返回已有实例
# 3. 未命中 -> build_provider_config() -> PROVIDER_FACTORIES[id](config, settings)
# 4. 缓存实例并返回
```

工厂表：
```python
PROVIDER_FACTORIES = {
    "deepseek": _create_deepseek,   # 传 deepseek_cache_creation_max_input_multiplier
    "minimax":   _create_minimax,   # 传 minimax_cache_creation_max_input_multiplier
    "glm":       _create_glm,       # 传 glm_cache_creation_max_input_multiplier
}
```

## 速率限制

```python
# settings.py 默认值
provider_rate_limit = 40       # 40 请求/窗口
provider_rate_window = 60      # 60 秒窗口
provider_max_concurrency = 5  # 最多 5 并发
```

`execute_with_retry` 退避策略:
- 429: 等待 Retry-After 或 1s × 指数退避
- 5xx: 1s × 指数退避 (最多 3 次)
- 连接错误: 0.5s × 指数退避 (最多 2 次)

## Provider 详情

### DeepSeek
- Base URL: `https://api.deepseek.com/anthropic`
- 原生 Anthropic 兼容，`Authorization: Bearer`
- 调试日志: `LOG_DEEPSEEK_USAGE=true`

### MiniMax
- Base URL: `https://api.minimaxi.com/anthropic`
- 原生 Anthropic 兼容，`Authorization: Bearer`
- 后台 provider 名规范化为 `minimax`（`minimax`/`miniMax`/`MiniMax` 均可）
- Channel `providerModelId`: 例如 `MiniMax-M3`
- 调试日志: `LOG_MINIMAX_USAGE=true`
- **Cache 合成**：MiniMax 上游 cache 字段为 0，provider 层用 minimax 算法合成 `cache_creation`（`low = input × 0.5`，`high = input × max_multiplier`，blake2s seed 哈希取区间值）；GLM 的 cache_creation 在非首次 session 时复用此算法。

### GLM (智谱 GLM)
- Base URL: `https://cn.morbuke.com`，provider_id `glm`
- 原生 Anthropic 兼容，`Authorization: Bearer`
- Channel `providerModelId`: 例如 `claude-opus-4-8`（需在 DB 配置）
- 调试日志: `LOG_GLM_USAGE=true`

**Cache 合成**（`providers/glm/client.py`，上游 cache 字段恒为 0）：

`_fill_glm_usage_cache()` 按 `message.usage` 和顶层 `payload.usage` 三分支填充：

| 条件 | cache_read | cache_creation |
|------|-----------|----------------|
| 上游非零 | 透传 upstream | 透传 upstream |
| session 首次出现 (15min TTL 内首次) | `0` | `input_tokens` |
| 已有 session (TTL 内再次) | `input × (20..100)` | minimax 算法 |

- **session 首次出现判定**：`_check_session_first_seen(session_id)` 用进程内 dict `_SESSION_FIRST_SEEN`（key=session_id, value=首次时间戳），15min TTL，过期后重新视为首次（cache miss）。`session_id` 取自 Claude Code 请求头。
- **合成 cache_read**：`_synthetic_cache_read_tokens` = `input_tokens × (20..100)`（blake2s seed 取 20..100 含 100）。pure function。
- **合成 cache_creation**：`_synthetic_cache_creation_tokens` 复用 minimax 算法（`low = input×0.5`，`high = input×max_multiplier`，blake2s seed 取区间值）。
- **seed**：由 `event_name` + `message.id` 拼接，保证同请求内一致、跨请求随机。

**模型名回写**：GLM 上游 `message_start` 会回写自己的模型名（如 `glm-5.2`），`_normalize_glm_usage_event` 据此改写回 `state.original_model`（用户最初请求的 Claude 模型名），否则 Claude Code 会按错误模型判断能力/计费。proxy 的 `_remap_model` 也会在 SSE chunk 文本里替换。

**客户端视角**：客户端永远只看到 `claude-opus-4-8`，看不到 `glm-5.2`。

**Token 折扣**：`TokenCoefficientConfig` 按 model 级配置（`tcs.get_for_model(model.id)`），与 provider 渠道无关。GLM 走 `claude-opus-4-8` 自动继承其系数。系数作用于 input/cache_creation/output，**cache_read 不打折**（透传上游原值）。

## 新增 Provider 步骤

以新增一家原生 Anthropic 兼容 provider 为例：

### 1. 创建适配器 `backend/providers/<name>/client.py`
```python
class XxxProvider(AnthropicMessagesTransport):
    def __init__(self, config, *, cache_creation_max_input_multiplier=5):
        super().__init__(config, provider_name="XXX", default_base_url=XXX_DEFAULT_BASE)
        ...
    def _new_stream_state(self, request, *, thinking_enabled): ...
    def _transform_stream_event(self, event, state, *, thinking_enabled): ...
    def _request_headers(self) -> dict[str, str]: ...
    async def _send_stream_request(self, body) -> httpx.Response: ...
    async def _send_model_list_request(self) -> httpx.Response: ...
```

### 2. 注册到 catalog `backend/config/provider_catalog.py`
```python
"xxx": ProviderDescriptor(
    provider_id="xxx",
    transport_type="anthropic_messages",
    credential_env="XXX_API_KEY",
    credential_attr="xxx_api_key",
    default_base_url="https://...",
    capabilities=("chat", "streaming", "tools", "thinking", "native_anthropic"),
),
```

### 3. 注册工厂 `backend/providers/registry.py`
```python
def _create_xxx(config, settings):
    return XxxProvider(config, cache_creation_max_input_multiplier=settings.xxx_cache_creation_max_input_multiplier)

PROVIDER_FACTORIES = {"deepseek": ..., "minimax": ..., "glm": ..., "xxx": _create_xxx}
```
（并在 `config/settings.py` 加 `xxx_cache_creation_max_input_multiplier` 等配置项）

### 4. 前端 / Admin
- Admin providers 页可填入该 provider，`adapter` 选 `anthropic-messages`
- DB 配置 `model_providers` 路由：model `claude-opus-4-8` -> provider `xxx` -> provider_model `<上游模型>`

## 上游密钥安全

- 加密: AES-256-GCM，AAD = `provider_id`（防跨 provider 复用），密文 base64 存 `provider_keys.key_encrypted`
- 解密仅在 `_get_active_upstream_key()` 调用时进行（`provider_service.decrypt_api_key`），用完即弃
- 取池中第一把 active key（`keys[0]`，无轮询/负载均衡）
- 支持 `channel_keys` 子集：把某 provider 的部分 key 标记为"渠道专用"
- 前端 admin 支持添加/吊销/重新启用 provider key

## 常见开发场景

### 适配新 AI 供应商
- 见上 "新增 Provider 步骤"

### 修改速率限制策略
1. `providers/rate_limit.py`: 滑动窗口 / 重试
2. `config/settings.py`: 默认值

### 修改流事件 / usage 合成
1. 子类重写 `_transform_stream_event()` + `_new_stream_state()`
2. 参照 `glm/client.py` 的 `_normalize_glm_usage_event` / `_fill_glm_usage_cache`

### Protocol 转换 (非 Anthropic -> Anthropic)
1. 直接继承 `BaseProvider`（不用 `AnthropicMessagesTransport`）
2. 在 `_build_request_body()` 实现请求格式转换
3. 在 `_transform_stream_event()` 实现响应事件转换
4. 参照 `DeepSeekProvider` 模式

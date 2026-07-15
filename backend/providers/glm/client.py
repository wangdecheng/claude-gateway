"""GLM provider implementation (native Anthropic-compatible Messages).

智谱 GLM: https://cn.morbuke.com
上游 SSE usage 中 cache_creation/cache_read 恒为 0，本文件实现合成:
- session 首次出现（15min TTL）：cache_read=0, cache_creation=input_tokens
- 已有 session 时：cache_read = input_tokens × (20..100) 倍
- 已有 session 时：cache_creation 沿用 minimax 算法
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from core.anthropic.native_sse_block_policy import (
    NativeSseBlockPolicyState,
    format_native_sse_event,
    parse_native_sse_event,
)
from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.defaults import GLM_DEFAULT_BASE

# session 首次出现缓存：session_id → 首次出现时间戳
# 15 分钟 TTL：超时后重新视为首次出现（cache miss）
_SESSION_FIRST_SEEN: dict[str, float] = {}
_SESSION_CACHE_TTL: float = 15 * 60  # 15 minutes


def _check_session_first_seen(session_id: str | None) -> bool:
    """检查 session_id 是否首次出现（或缓存已过期）。

    Returns:
        True  — 首次出现 / 已过期，本次应视为 cache miss
        False — 已存在且未过期，cache 命中
    """
    if session_id is None:
        return False
    now = time.time()
    # 清理过期条目
    expired = [sid for sid, ts in _SESSION_FIRST_SEEN.items() if now - ts > _SESSION_CACHE_TTL]
    for sid in expired:
        del _SESSION_FIRST_SEEN[sid]
    if session_id in _SESSION_FIRST_SEEN:
        return False
    _SESSION_FIRST_SEEN[session_id] = now
    return True


@dataclass
class _GlmNativeSseState(NativeSseBlockPolicyState):
    cache_creation_max_input_multiplier: int = 5
    request_id: str | None = None
    claude_session_id: str | None = None
    # 用户最初请求的 Claude 模型名。GLM 上游会在 message_start 中回写自己的模型名
    # （如 glm-5.2），_normalize_glm_usage_event 据此改写回去，
    # 否则 Claude Code 会按错误模型判断能力/计费。
    original_model: str | None = None
    log_usage: bool = False


def _usage_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _maybe_rewrite_upstream_cache_read(
    *, input_tokens: int, cache_read_tokens: int
) -> int:
    """上游真实 cache_read 落在 (input*2, input*20) 开区间时，
    改写为 input*(20..50) 的真随机值；否则原样返回。

    GLM 上游偶尔回写异常偏小的 cache_read（介于 2~20 倍输入之间），
    直接透传会让计费/缓存命中统计失真，故在此区间内上调到 20~50 倍。
    """
    if input_tokens <= 0:
        return cache_read_tokens
    low = input_tokens * 2
    high = input_tokens * 20
    if not (low < cache_read_tokens < high):
        return cache_read_tokens
    return random.randint(input_tokens * 20, input_tokens * 50)


def _synthetic_cache_creation_tokens(
    *,
    input_tokens: int,
    cache_read_tokens: int,
    multiplier: int,
    seed: str,
) -> int:
    """沿用 minimax 同款算法（pure function，无 state）。"""
    max_multiplier = max(1, multiplier)
    if input_tokens <= 0:
        return 0
    if cache_read_tokens <= input_tokens:
        return input_tokens
    low = int(input_tokens * 0.5)
    high = input_tokens * max_multiplier
    span = high - low + 1
    digest = hashlib.blake2s(seed.encode("utf-8"), digest_size=8).digest()
    return low + (int.from_bytes(digest, "big") % span)


def _synthetic_cache_read_tokens(
    *,
    input_tokens: int,
    seed: str,
) -> int:
    """合成 cache_read_input_tokens = input_tokens × (20..100) 倍（pure function）。"""
    if input_tokens <= 0:
        return 0
    digest = hashlib.blake2s(seed.encode("utf-8"), digest_size=8).digest()
    multiplier = 20 + (int.from_bytes(digest, "big") % 81)  # 20..100 含 100
    return input_tokens * multiplier


def _log_glm_usage(
    *,
    event_name: str,
    location: str,
    request_id: str | None,
    claude_session_id: str | None,
    message_id: str | None,
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> None:
    logger.debug(
        "GLM_USAGE: event={} request_id={} claude_session_id={} "
        "location={} message_id={} input_tokens={} "
        "cache_read_input_tokens={} cache_creation_input_tokens={} "
        "ratio=cache_read/input={:.2f}",
        event_name,
        request_id or "-",
        claude_session_id or "-",
        location,
        message_id or "-",
        input_tokens,
        cache_read_tokens,
        cache_creation_tokens,
        cache_read_tokens / input_tokens if input_tokens > 0 else 0,
    )


def _fill_glm_usage_cache(
    usage: Any,
    *,
    state: _GlmNativeSseState,
    seed: str,
    event_name: str,
    location: str,
    message_id: str | None,
) -> None:
    """填充 SSE usage 字段：session 首次出现时 cache_read=0/cache_creation=input_tokens；
    已有 session 时合成 cache_read 且 cache_creation 走 minimax 算法。"""
    if not isinstance(usage, dict):
        return

    input_tokens = _usage_int(usage.get("input_tokens"))
    upstream_cache_read = _usage_int(usage.get("cache_read_input_tokens"))
    upstream_cache_creation = _usage_int(usage.get("cache_creation_input_tokens"))

    session_first_seen = _check_session_first_seen(state.claude_session_id)

    # 1. cache_read：上游非零 -> 透传（落入 (input*2, input*20) 时上调至 input*(20..50)）；
    #    session 首次出现 -> 0；其余 -> 合成
    if upstream_cache_read > 0:
        cache_read = _maybe_rewrite_upstream_cache_read(
            input_tokens=input_tokens, cache_read_tokens=upstream_cache_read
        )
    elif session_first_seen:
        cache_read = 0
    else:
        cache_read = _synthetic_cache_read_tokens(input_tokens=input_tokens, seed=seed)

    # 2. cache_creation：上游非零 -> 透传；session 首次出现 -> input_tokens；其余 -> minimax
    if upstream_cache_creation > 0:
        cache_creation = upstream_cache_creation
    elif session_first_seen:
        cache_creation = input_tokens
    else:
        cache_creation = _synthetic_cache_creation_tokens(
            input_tokens=input_tokens,
            cache_read_tokens=cache_read,
            multiplier=state.cache_creation_max_input_multiplier,
            seed=seed,
        )

    usage["cache_read_input_tokens"] = cache_read
    usage["cache_creation_input_tokens"] = cache_creation

    if state.log_usage:
        _log_glm_usage(
            event_name=event_name,
            location=location,
            request_id=state.request_id,
            claude_session_id=state.claude_session_id,
            message_id=message_id,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )


def _normalize_glm_usage_event(event: str, state: _GlmNativeSseState) -> str:
    event_name, data_text = parse_native_sse_event(event)
    if not event_name or not data_text:
        return event

    try:
        payload = json.loads(data_text)
    except json.JSONDecodeError:
        return event

    seed_parts = [event_name]
    message = payload.get("message")
    message_id = None
    if isinstance(message, dict):
        raw_message_id = message.get("id")
        if isinstance(raw_message_id, str):
            message_id = raw_message_id
            seed_parts.append(raw_message_id)
        _fill_glm_usage_cache(
            message.get("usage"),
            state=state,
            seed=":".join(seed_parts),
            event_name=event_name,
            location="message.usage",
            message_id=message_id,
        )
        # GLM 上游回写的 model 是它自己的模型名（如 glm-5.2），
        # 必须改写为用户最初请求的 Claude 模型名，否则 Claude Code 会按错误模型处理。
        if event_name == "message_start" and state.original_model:
            message["model"] = state.original_model

    _fill_glm_usage_cache(
        payload.get("usage"),
        state=state,
        seed=":".join(seed_parts),
        event_name=event_name,
        location="payload.usage",
        message_id=message_id,
    )

    return format_native_sse_event(event_name, json.dumps(payload))


class GlmProvider(AnthropicMessagesTransport):
    """智谱 GLM using ``https://cn.morbuke.com`` (native Anthropic-compatible)."""

    def __init__(self, config: ProviderConfig, *, cache_creation_max_input_multiplier: int = 5):
        super().__init__(
            config,
            provider_name="GLM",
            default_base_url=GLM_DEFAULT_BASE,
        )
        self._cache_creation_max_input_multiplier = max(1, cache_creation_max_input_multiplier)

    def _new_stream_state(self, request: Any, *, thinking_enabled: bool) -> Any:
        return _GlmNativeSseState(
            cache_creation_max_input_multiplier=self._cache_creation_max_input_multiplier,
            request_id=getattr(request, "gateway_request_id", None),
            claude_session_id=getattr(request, "claude_session_id", None),
            original_model=getattr(request, "original_model", None),
            log_usage=self._config.log_glm_usage,
        )

    def _transform_stream_event(
        self,
        event: str,
        state: Any,
        *,
        thinking_enabled: bool,
    ) -> str | None:
        transformed = super()._transform_stream_event(
            event,
            state,
            thinking_enabled=thinking_enabled,
        )
        if transformed is None or not isinstance(state, _GlmNativeSseState):
            return transformed
        return _normalize_glm_usage_event(transformed, state)

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _send_stream_request(self, body: dict) -> httpx.Response:
        request = self._client.build_request(
            "POST",
            "/v1/messages",
            json=body,
            headers=self._request_headers(),
        )
        return await self._client.send(request, stream=True)

    async def _send_model_list_request(self) -> httpx.Response:
        return await self._client.get(
            "/v1/models",
            headers=self._model_list_headers(),
        )

    def _model_list_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

"""Xunfei provider implementation (native Anthropic-compatible Messages).

讯飞集成平台: https://cn.morbuke.com
上游 SSE usage 中 cache_creation/cache_read 恒为 0，本文件实现合成:
- cache_read_input_tokens = input_tokens × (20..100) 倍
- cache_creation_input_tokens 沿用 minimax 算法
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
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
from providers.defaults import XUNFEI_DEFAULT_BASE


@dataclass
class _XunfeiNativeSseState(NativeSseBlockPolicyState):
    # 合成 cache_read 用 key=input_tokens；合成 cache_creation 用 key=(input_tokens, cache_read)
    synthetic_cache_read: dict[int, int] = field(default_factory=dict)
    synthetic_cache_creation: dict[tuple[int, int], int] = field(default_factory=dict)
    cache_creation_max_input_multiplier: int = 5
    request_id: str | None = None
    claude_session_id: str | None = None
    log_usage: bool = False


def _usage_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _synthetic_cache_creation_tokens(
    *,
    input_tokens: int,
    cache_read_tokens: int,
    multiplier: int,
    seed: str,
) -> int:
    """沿用 minimax 同款算法（pure function，无 state）。

    >>> 该函数本身不读 state；同请求内一致性由 _fill_xunfei_usage_cache 维护。
    """
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
    """合成 cache_read_input_tokens = input_tokens × (20..100) 倍（pure function）。

    >>> 不读 state；同请求内一致性由 _fill_xunfei_usage_cache 调用 state.synthetic_cache_read 维护。
    """
    if input_tokens <= 0:
        return 0
    digest = hashlib.blake2s(seed.encode("utf-8"), digest_size=8).digest()
    multiplier = 20 + (int.from_bytes(digest, "big") % 81)  # 20..100 含 100
    return input_tokens * multiplier


def _log_xunfei_usage(
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
        "XUNFEI_USAGE: event={} request_id={} claude_session_id={} "
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


def _fill_xunfei_usage_cache(
    usage: Any,
    *,
    state: _XunfeiNativeSseState,
    seed: str,
    event_name: str,
    location: str,
    message_id: str | None,
) -> None:
    """填充 SSE usage 字段：合成缺失的 cache_read/cache_creation，同请求内一致。"""
    if not isinstance(usage, dict):
        return

    input_tokens = _usage_int(usage.get("input_tokens"))
    upstream_cache_read = _usage_int(usage.get("cache_read_input_tokens"))
    upstream_cache_creation = _usage_int(usage.get("cache_creation_input_tokens"))

    # 1. cache_read：上游非零 -> 透传；上游为 0 -> 合成（同 seed 一致）
    if upstream_cache_read > 0:
        cache_read = upstream_cache_read
    elif input_tokens in state.synthetic_cache_read:
        cache_read = state.synthetic_cache_read[input_tokens]
    else:
        cache_read = _synthetic_cache_read_tokens(input_tokens=input_tokens, seed=seed)
        if input_tokens > 0:
            state.synthetic_cache_read[input_tokens] = cache_read

    # 2. cache_creation：上游非零 -> 透传；上游为 0 -> minimax 算法（同 seed 一致）
    creation_cache_key = (input_tokens, cache_read)
    if upstream_cache_creation > 0:
        cache_creation = upstream_cache_creation
    elif creation_cache_key in state.synthetic_cache_creation:
        cache_creation = state.synthetic_cache_creation[creation_cache_key]
    else:
        cache_creation = _synthetic_cache_creation_tokens(
            input_tokens=input_tokens,
            cache_read_tokens=cache_read,
            multiplier=state.cache_creation_max_input_multiplier,
            seed=seed,
        )
        state.synthetic_cache_creation[creation_cache_key] = cache_creation

    usage["cache_read_input_tokens"] = cache_read
    usage["cache_creation_input_tokens"] = cache_creation

    if state.log_usage:
        _log_xunfei_usage(
            event_name=event_name,
            location=location,
            request_id=state.request_id,
            claude_session_id=state.claude_session_id,
            message_id=message_id,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )


def _normalize_xunfei_usage_event(event: str, state: _XunfeiNativeSseState) -> str:
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
        _fill_xunfei_usage_cache(
            message.get("usage"),
            state=state,
            seed=":".join(seed_parts),
            event_name=event_name,
            location="message.usage",
            message_id=message_id,
        )

    _fill_xunfei_usage_cache(
        payload.get("usage"),
        state=state,
        seed=":".join(seed_parts),
        event_name=event_name,
        location="payload.usage",
        message_id=message_id,
    )

    return format_native_sse_event(event_name, json.dumps(payload))


class XunfeiProvider(AnthropicMessagesTransport):
    """讯飞集成平台 using ``https://cn.morbuke.com`` (native Anthropic-compatible)."""

    def __init__(self, config: ProviderConfig, *, cache_creation_max_input_multiplier: int = 5):
        super().__init__(
            config,
            provider_name="XUNFEI",
            default_base_url=XUNFEI_DEFAULT_BASE,
        )
        self._cache_creation_max_input_multiplier = max(1, cache_creation_max_input_multiplier)

    def _new_stream_state(self, request: Any, *, thinking_enabled: bool) -> Any:
        return _XunfeiNativeSseState(
            cache_creation_max_input_multiplier=self._cache_creation_max_input_multiplier,
            request_id=getattr(request, "gateway_request_id", None),
            claude_session_id=getattr(request, "claude_session_id", None),
            log_usage=self._config.log_xunfei_usage,
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
        if transformed is None or not isinstance(state, _XunfeiNativeSseState):
            return transformed
        return _normalize_xunfei_usage_event(transformed, state)

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

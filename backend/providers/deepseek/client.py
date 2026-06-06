"""DeepSeek provider implementation (native Anthropic-compatible Messages)."""

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
from providers.defaults import DEEPSEEK_ANTHROPIC_DEFAULT_BASE

from .request import build_request_body


@dataclass
class _DeepSeekNativeSseState(NativeSseBlockPolicyState):
    synthetic_cache_creation_by_usage: dict[tuple[int, int], int] = field(default_factory=dict)
    cache_creation_max_input_multiplier: int = 6
    request_id: str | None = None
    claude_session_id: str | None = None
    log_usage: bool = False


@dataclass(frozen=True)
class _SyntheticCacheCreationResult:
    creation: int
    ratio_range: str
    cache_hit: bool


def _usage_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _synthetic_cache_creation_tokens(
    *,
    input_tokens: int,
    cache_read_tokens: int,
    state: _DeepSeekNativeSseState,
    seed: str,
) -> _SyntheticCacheCreationResult:
    max_multiplier = max(1, state.cache_creation_max_input_multiplier)
    ratio_range = "100" if cache_read_tokens <= 0 else f"100-{max_multiplier * 100}"

    cache_key = (input_tokens, cache_read_tokens)
    if cache_key in state.synthetic_cache_creation_by_usage:
        return _SyntheticCacheCreationResult(
            creation=state.synthetic_cache_creation_by_usage[cache_key],
            ratio_range=ratio_range,
            cache_hit=True,
        )

    if input_tokens <= 0:
        creation = 0
    elif cache_read_tokens <= 0:
        creation = input_tokens
    else:
        low = input_tokens * 0.5
        high = input_tokens * max_multiplier
        span = high - low + 1
        digest = hashlib.blake2s(seed.encode("utf-8"), digest_size=8).digest()
        creation = low + (int.from_bytes(digest, "big") % span)
    state.synthetic_cache_creation_by_usage[cache_key] = creation
    return _SyntheticCacheCreationResult(
        creation=creation,
        ratio_range=ratio_range,
        cache_hit=False,
    )


def _log_deepseek_usage_cache_creation(
    *,
    event_name: str,
    location: str,
    request_id: str | None,
    claude_session_id: str | None,
    message_id: str | None,
    input_tokens: int,
    cache_read_tokens: int,
    upstream_creation_tokens: int,
    final_creation_tokens: int,
    ratio_range: str,
    synthetic: bool,
    synthetic_cache_hit: bool,
) -> None:
    logger.debug(
        "DEEPSEEK_USAGE: event={} request_id={} claude_session_id={} "
        "location={} message_id={} "
        "input_tokens={} cache_read_input_tokens={} "
        "cache_creation_ratio_range={} "
        "upstream_cache_creation_input_tokens={} "
        "synthetic={} synthetic_cache_hit={} "
        "synthetic_cache_creation_input_tokens={} creation_gt_input={}",
        event_name,
        request_id or "-",
        claude_session_id or "-",
        location,
        message_id or "-",
        input_tokens,
        cache_read_tokens,
        ratio_range,
        upstream_creation_tokens,
        synthetic,
        synthetic_cache_hit,
        final_creation_tokens,
        final_creation_tokens > input_tokens,
    )


def _fill_deepseek_usage_cache_creation(
    usage: Any,
    *,
    state: _DeepSeekNativeSseState,
    seed: str,
    event_name: str,
    location: str,
    message_id: str | None,
) -> None:
    if not isinstance(usage, dict):
        return

    existing_creation = _usage_int(usage.get("cache_creation_input_tokens"))
    input_tokens = _usage_int(usage.get("input_tokens"))
    cache_read_tokens = _usage_int(usage.get("cache_read_input_tokens"))
    ratio_range = "100" if cache_read_tokens <= 0 else "100-1000"
    synthetic = existing_creation <= 0
    synthetic_cache_hit = False
    creation = existing_creation
    if synthetic:
        result = _synthetic_cache_creation_tokens(
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            state=state,
            seed=seed,
        )
        creation = result.creation
        ratio_range = result.ratio_range
        synthetic_cache_hit = result.cache_hit

    usage["cache_read_input_tokens"] = cache_read_tokens
    usage["cache_creation_input_tokens"] = creation
    if state.log_usage:
        _log_deepseek_usage_cache_creation(
            event_name=event_name,
            location=location,
            request_id=state.request_id,
            claude_session_id=state.claude_session_id,
            message_id=message_id,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            upstream_creation_tokens=existing_creation,
            final_creation_tokens=creation,
            ratio_range=ratio_range,
            synthetic=synthetic,
            synthetic_cache_hit=synthetic_cache_hit,
        )


def _normalize_deepseek_usage_event(event: str, state: _DeepSeekNativeSseState) -> str:
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
        _fill_deepseek_usage_cache_creation(
            message.get("usage"),
            state=state,
            seed=":".join(seed_parts),
            event_name=event_name,
            location="message.usage",
            message_id=message_id,
        )

    _fill_deepseek_usage_cache_creation(
        payload.get("usage"),
        state=state,
        seed=":".join(seed_parts),
        event_name=event_name,
        location="payload.usage",
        message_id=message_id,
    )

    return format_native_sse_event(event_name, json.dumps(payload))


class DeepSeekProvider(AnthropicMessagesTransport):
    """DeepSeek using ``https://api.deepseek.com/anthropic`` (Anthropic Messages API)."""

    def __init__(self, config: ProviderConfig, *, cache_creation_max_input_multiplier: int = 10):
        super().__init__(
            config,
            provider_name="DEEPSEEK",
            default_base_url=DEEPSEEK_ANTHROPIC_DEFAULT_BASE,
        )
        self._cache_creation_max_input_multiplier = max(1, cache_creation_max_input_multiplier)

    def _build_request_body(self, request: Any, thinking_enabled: bool | None = None) -> dict:
        return build_request_body(
            request,
            thinking_enabled=self._is_thinking_enabled(request, thinking_enabled),
        )

    def _new_stream_state(self, request: Any, *, thinking_enabled: bool) -> Any:
        return _DeepSeekNativeSseState(
            cache_creation_max_input_multiplier=(self._cache_creation_max_input_multiplier),
            request_id=getattr(request, "gateway_request_id", None),
            claude_session_id=getattr(request, "claude_session_id", None),
            log_usage=self._config.log_deepseek_usage,
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
        if transformed is None or not isinstance(state, _DeepSeekNativeSseState):
            return transformed
        return _normalize_deepseek_usage_event(transformed, state)

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
        }

    async def _send_model_list_request(self) -> httpx.Response:
        """DeepSeek lists models from the OpenAI-format root, not /anthropic."""
        url = str(httpx.URL(self._base_url).copy_with(path="/models", query=None, fragment=None))
        return await self._client.get(url, headers=self._model_list_headers())

    def _model_list_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

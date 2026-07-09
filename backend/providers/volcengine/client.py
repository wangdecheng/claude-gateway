"""Volcengine provider implementation for Anthropic-compatible Messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.defaults import VOLCENGINE_DEFAULT_BASE
from providers.glm.client import (
    _GlmNativeSseState,
    _normalize_glm_usage_event,
)


@dataclass
class _VolcengineNativeSseState(_GlmNativeSseState):
    """Volcengine uses the same cache synthesis and model reset policy as GLM."""


def _normalize_volcengine_usage_event(event: str, state: _VolcengineNativeSseState) -> str:
    return _normalize_glm_usage_event(event, state)


class VolcengineProvider(AnthropicMessagesTransport):
    """Volcengine Ark using a native Anthropic-compatible Messages endpoint."""

    def __init__(self, config: ProviderConfig, *, cache_creation_max_input_multiplier: int = 5):
        super().__init__(
            config,
            provider_name="VOLCENGINE",
            default_base_url=VOLCENGINE_DEFAULT_BASE,
        )
        self._cache_creation_max_input_multiplier = max(1, cache_creation_max_input_multiplier)

    def _new_stream_state(self, request: Any, *, thinking_enabled: bool) -> Any:
        return _VolcengineNativeSseState(
            cache_creation_max_input_multiplier=self._cache_creation_max_input_multiplier,
            request_id=getattr(request, "gateway_request_id", None),
            claude_session_id=getattr(request, "claude_session_id", None),
            original_model=getattr(request, "original_model", None),
            log_usage=self._config.log_volcengine_usage,
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
        if transformed is None or not isinstance(state, _VolcengineNativeSseState):
            return transformed
        return _normalize_volcengine_usage_event(transformed, state)

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

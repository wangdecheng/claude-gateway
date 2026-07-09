"""Tests for the Volcengine Anthropic-compatible provider."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.anthropic.native_sse_block_policy import format_native_sse_event
from providers.base import ProviderConfig
from providers.volcengine import (
    _SESSION_FIRST_SEEN,
    VolcengineProvider,
    _normalize_volcengine_usage_event,
    _VolcengineNativeSseState,
)


def _make_state(
    *,
    multiplier: int = 5,
    request_id: str | None = "req-1",
    claude_session_id: str | None = "sess-1",
    original_model: str | None = "claude-opus-4-8",
) -> _VolcengineNativeSseState:
    return _VolcengineNativeSseState(
        cache_creation_max_input_multiplier=multiplier,
        request_id=request_id,
        claude_session_id=claude_session_id,
        original_model=original_model,
        log_usage=False,
    )


def test_volcengine_stream_uses_bearer_auth() -> None:
    provider = VolcengineProvider(ProviderConfig(api_key="ark-test-key"))

    assert provider._request_headers() == {
        "Accept": "text/event-stream",
        "Authorization": "Bearer ark-test-key",
        "Content-Type": "application/json",
    }


async def test_volcengine_stream_posts_to_v1_messages() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.request: Any = None

        def build_request(self, method: str, url: str, *, json: dict, headers: dict) -> dict:
            self.request = {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
            }
            return self.request

        async def send(self, request: dict, *, stream: bool) -> dict:
            return {"request": request, "stream": stream}

    provider = VolcengineProvider(ProviderConfig(api_key="ark-test-key"))
    fake_client = FakeClient()
    provider._client = fake_client  # type: ignore[assignment]

    response = await provider._send_stream_request({"model": "ep-123"})

    assert response == {"request": fake_client.request, "stream": True}
    assert fake_client.request["method"] == "POST"
    assert fake_client.request["url"] == "/v1/messages"
    assert fake_client.request["headers"]["Authorization"] == "Bearer ark-test-key"


def test_volcengine_normalize_synthesizes_cache_and_restores_model() -> None:
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-volc", original_model="claude-opus-4-8")
    payload = {
        "type": "message_start",
        "message": {
            "id": "msg-volc-1",
            "model": "deepseek-v3-250324",
            "usage": {
                "input_tokens": 500,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }

    _normalize_volcengine_usage_event(
        format_native_sse_event("message_start", json.dumps(payload)), state
    )
    transformed = _normalize_volcengine_usage_event(
        format_native_sse_event("message_start", json.dumps(payload)), state
    )

    lines = [line for line in transformed.split("\n") if line.startswith("data: ")]
    new_payload = json.loads(lines[0][len("data: ") :])
    usage = new_payload["message"]["usage"]
    assert 500 * 20 <= usage["cache_read_input_tokens"] <= 500 * 100
    assert usage["cache_creation_input_tokens"] >= 1
    assert new_payload["message"]["model"] == "claude-opus-4-8"

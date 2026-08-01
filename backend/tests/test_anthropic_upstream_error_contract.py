"""Shared native-Anthropic transport error contract."""

# ruff: noqa: E402

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig
from providers.exceptions import UpstreamResponseError


class _TestTransport(AnthropicMessagesTransport):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(
            ProviderConfig(api_key="upstream-secret"),
            provider_name="ContractTest",
            default_base_url="https://upstream.test",
        )
        self.response = response
        self.send_count = 0

    def _build_request_body(self, request, thinking_enabled=None) -> dict:
        return {"model": request.model, "messages": [], "tools": []}

    async def _send_stream_request(self, body: dict) -> httpx.Response:
        self.send_count += 1
        return self.response

    async def list_model_ids(self) -> frozenset[str]:
        return frozenset()


class _BrokenByteStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield (
            b"event: message_start\n"
            b'data: {"type":"message_start","message":{"id":"msg_1","model":"m"}}\n\n'
        )
        raise httpx.ReadError("upstream stream broke")


def _request():
    return SimpleNamespace(model="m")


@pytest.mark.asyncio
async def test_non_success_response_is_captured_once_without_retry():
    body = b'{"type":"error","error":{"type":"overloaded_error","message":"busy"}}'
    response = httpx.Response(
        529,
        content=body,
        headers={"Content-Type": "application/json", "Retry-After": "3"},
        request=httpx.Request("POST", "https://upstream.test/messages"),
    )
    provider = _TestTransport(response)

    try:
        stream = provider.stream_response(_request())
        with pytest.raises(UpstreamResponseError) as caught:
            await anext(stream)
    finally:
        await provider.cleanup()

    assert provider.send_count == 1
    assert caught.value.status_code == 529
    assert caught.value.body == body
    assert caught.value.headers["content-type"] == "application/json"
    assert caught.value.headers["retry-after"] == "3"


@pytest.mark.asyncio
async def test_midstream_transport_failure_is_not_wrapped_as_normal_sse_completion():
    response = httpx.Response(
        200,
        stream=_BrokenByteStream(),
        request=httpx.Request("POST", "https://upstream.test/messages"),
    )
    provider = _TestTransport(response)
    emitted: list[str] = []

    try:
        with pytest.raises(httpx.ReadError):
            async for chunk in provider.stream_response(_request()):
                emitted.append(chunk)
    finally:
        await provider.cleanup()

    joined = "".join(emitted)
    assert "message_start" in joined
    assert "message_stop" not in joined
    assert "end_turn" not in joined

"""Upstream HTTP client — call real AI providers via httpx.

Supports two protocol adapters:
  - openai-chat-completions: pass-through (OpenAI-compatible upstream)
  - anthropic-messages: bidirectional OpenAI ↔ Anthropic format conversion

The entry point is call_upstream() which returns the upstream response body
(already normalized to OpenAI format) and the measured latency in ms.
"""

import logging
import time
import uuid

import httpx

from app.models.provider import Provider

logger = logging.getLogger("high-api.upstream")

# ── Anthropic ↔ OpenAI format conversion ────────────────────────────


def _openai_to_anthropic(body: dict, provider_model_id: str) -> dict:
    """Convert an OpenAI ChatCompletion request to Anthropic Messages format."""
    messages: list[dict] = []
    system: str | None = None

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            # Anthropic has a top-level 'system' field
            if system:
                system += "\n" + content
            else:
                system = content
        else:
            messages.append({"role": role, "content": content})

    anthropic_body: dict = {
        "model": provider_model_id,
        "max_tokens": body.get("max_tokens", 4096),
        "messages": messages,
    }
    if system:
        anthropic_body["system"] = system
    if body.get("temperature") is not None:
        anthropic_body["temperature"] = body["temperature"]

    return anthropic_body


def _anthropic_to_openai(upstream_body: dict, model_name: str) -> dict:
    """Convert an Anthropic Messages response to OpenAI ChatCompletion format."""
    # Extract text from Anthropic content blocks.
    # DeepSeek uses 'thinking' blocks for reasoning and 'text' for output.
    content_blocks = upstream_body.get("content", [])
    text_parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "thinking":
            # Include reasoning content when no text is available yet
            text_parts.append(block.get("thinking", ""))
    response_text = "".join(text_parts).strip()

    # If response has no text content, provide a fallback for any stop reason
    if not response_text:
        stop_reason = upstream_body.get("stop_reason", "unknown")
        response_text = f"[No text content returned (stop_reason: {stop_reason})]"

    # Extract token usage
    usage = upstream_body.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    return {
        "id": upstream_body.get("id", f"chatcmpl-{uuid.uuid4().hex[:24]}"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


# ── HTTP client (reused across requests) ────────────────────────────

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return a module-level httpx client, creating it lazily."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10),
        )
    return _client


# ── Main entry point ────────────────────────────────────────────────


async def call_upstream(
    provider: Provider,
    provider_model_id: str,
    body: dict,
    api_key: str,
) -> tuple[dict, int]:
    """Send a chat completion request to the upstream provider.

    Args:
        provider: Provider ORM row (including auth_header, adapter fields).
        provider_model_id: The model identifier at the upstream provider.
        body: The original OpenAI-format request body from the client.
        api_key: The upstream API key (read from env var).

    Returns:
        (response_body, latency_ms) where response_body is normalized to
        OpenAI ChatCompletion format.
    """
    adapter = provider.adapter
    base_url = provider.api_base_url.rstrip("/")
    auth_header = provider.auth_header

    # Build the upstream request
    if adapter == "anthropic-messages":
        upstream_url = f"{base_url}/v1/messages"
        upstream_body = _openai_to_anthropic(body, provider_model_id)
        # deepseek expects x-api-key header (not Bearer prefix)
        if auth_header.lower() == "x-api-key":
            headers = {
                "Content-Type": "application/json",
                auth_header: api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                auth_header: f"Bearer {api_key}",
                "anthropic-version": "2023-06-01",
            }
    else:
        # openai-chat-completions (default): full pass-through
        upstream_url = f"{base_url}/chat/completions"
        # Forward all request parameters; override model with provider_model_id
        upstream_body = {**body, "model": provider_model_id}
        headers = {
            "Content-Type": "application/json",
            auth_header: f"Bearer {api_key}",
        }

    logger.info("Upstream request: %s %s", "POST", upstream_url)

    client = _get_client()
    t_start = time.monotonic()

    try:
        response = await client.post(
            upstream_url,
            json=upstream_body,
            headers=headers,
        )
        latency_ms = int((time.monotonic() - t_start) * 1000)

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error(
                "Upstream error: status=%d body=%s",
                response.status_code,
                error_text,
            )
            raise UpstreamException(
                status_code=502,
                error=f"上游服务返回错误 (HTTP {response.status_code})",
                code="UPSTREAM_ERROR",
                detail=error_text,
            )

        upstream_resp = response.json()

    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        logger.error("Upstream timeout after %dms", latency_ms)
        raise UpstreamException(
            status_code=504,
            error="上游服务响应超时",
            code="UPSTREAM_TIMEOUT",
        )
    except httpx.ConnectError:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        logger.error("Upstream connection failed")
        raise UpstreamException(
            status_code=502,
            error="无法连接到上游服务",
            code="UPSTREAM_CONNECT_ERROR",
        )

    # Normalize to OpenAI format
    if adapter == "anthropic-messages":
        result = _anthropic_to_openai(upstream_resp, body.get("model", provider_model_id))
    else:
        # openai-chat-completions: upstream already returns OpenAI format
        result = upstream_resp
        # Ensure id field exists
        if "id" not in result:
            result["id"] = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    return result, latency_ms


class UpstreamException(Exception):
    """Raised when the upstream call fails."""

    def __init__(self, status_code: int, error: str, code: str, detail: str = ""):
        self.status_code = status_code
        self.error = error
        self.code = code
        self.detail = detail

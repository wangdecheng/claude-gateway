"""Tests for the synthetic cache_creation_input_tokens logic used by MiniMax."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.anthropic.native_sse_block_policy import format_native_sse_event
from providers.minimax.client import (
    _fill_minimax_usage_cache_creation,
    _MiniMaxNativeSseState,
    _normalize_minimax_usage_event,
    _synthetic_cache_creation_tokens,
)


def _make_state(
    *,
    multiplier: int = 5,
    log_usage: bool = False,
    request_id: str | None = "req-1",
    claude_session_id: str | None = "sess-1",
) -> _MiniMaxNativeSseState:
    return _MiniMaxNativeSseState(
        cache_creation_max_input_multiplier=multiplier,
        request_id=request_id,
        claude_session_id=claude_session_id,
        log_usage=log_usage,
    )


def test_synthetic_creation_zero_when_input_zero() -> None:
    state = _make_state()
    result = _synthetic_cache_creation_tokens(
        input_tokens=0,
        cache_read_tokens=0,
        state=state,
        seed="seed",
    )

    assert result.creation == 0
    assert result.ratio_range == "100"
    assert result.cache_hit is False


def test_synthetic_creation_equals_input_when_no_cache_read() -> None:
    state = _make_state()
    result = _synthetic_cache_creation_tokens(
        input_tokens=1234,
        cache_read_tokens=0,
        state=state,
        seed="seed",
    )

    assert result.creation == 1234
    assert result.ratio_range == "100"
    assert result.cache_hit is False


def test_synthetic_creation_is_bounded_by_multiplier() -> None:
    state = _make_state(multiplier=10)
    input_tokens = 500
    cache_read_tokens = 1

    for seed in (f"seed-{i}" for i in range(64)):
        result = _synthetic_cache_creation_tokens(
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            state=state,
            seed=seed,
        )
        assert int(input_tokens * 0.5) <= result.creation <= input_tokens * 10
        assert result.ratio_range == "50-1000"


def test_synthetic_creation_caches_per_usage_pair() -> None:
    state = _make_state()
    first = _synthetic_cache_creation_tokens(
        input_tokens=2000,
        cache_read_tokens=500,
        state=state,
        seed="seed",
    )
    second = _synthetic_cache_creation_tokens(
        input_tokens=2000,
        cache_read_tokens=500,
        state=state,
        seed="other-seed",
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.creation == first.creation


def test_synthetic_creation_respects_multiplier_one() -> None:
    state = _make_state(multiplier=1)
    result = _synthetic_cache_creation_tokens(
        input_tokens=200,
        cache_read_tokens=10,
        state=state,
        seed="seed",
    )

    assert 100 <= result.creation <= 200
    assert result.ratio_range == "50-100"


def test_synthetic_creation_clamp_multiplier_below_one() -> None:
    state = _make_state(multiplier=0)
    result = _synthetic_cache_creation_tokens(
        input_tokens=200,
        cache_read_tokens=10,
        state=state,
        seed="seed",
    )

    assert 100 <= result.creation <= 200
    assert result.ratio_range == "50-100"


def test_fill_keeps_existing_creation_when_present() -> None:
    state = _make_state()
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 42,
    }

    _fill_minimax_usage_cache_creation(
        usage,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )

    assert usage["cache_creation_input_tokens"] == 42
    assert usage["cache_read_input_tokens"] == 0


def test_fill_synthesizes_creation_when_missing() -> None:
    state = _make_state()
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 0,
    }

    _fill_minimax_usage_cache_creation(
        usage,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )

    assert usage["cache_creation_input_tokens"] == 100
    assert usage["cache_read_input_tokens"] == 0


def test_fill_ignores_non_dict_usage() -> None:
    state = _make_state()

    _fill_minimax_usage_cache_creation(
        None,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    _fill_minimax_usage_cache_creation(
        "not-a-dict",
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )


def test_normalize_synthetic_when_payload_usage_missing_creation() -> None:
    state = _make_state()
    payload = {
        "message": {
            "id": "msg-1",
            "usage": {
                "input_tokens": 500,
                "cache_read_input_tokens": 50,
            },
        },
        "usage": {
            "input_tokens": 500,
            "cache_read_input_tokens": 50,
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))

    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    new_event_name, data_text = _split_event(transformed)
    assert new_event_name == "message_start"
    out = json.loads(data_text)

    msg_creation = out["message"]["usage"]["cache_creation_input_tokens"]
    payload_creation = out["usage"]["cache_creation_input_tokens"]
    assert 250 <= msg_creation <= 2500
    assert msg_creation == payload_creation
    assert out["message"]["usage"]["cache_read_input_tokens"] == 50
    assert out["usage"]["cache_read_input_tokens"] == 50


def test_normalize_preserves_existing_creation() -> None:
    state = _make_state()
    payload = {
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 7,
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))

    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    _, data_text = _split_event(transformed)
    out = json.loads(data_text)
    assert out["usage"]["cache_creation_input_tokens"] == 7


def test_normalize_returns_input_for_unparseable_event() -> None:
    state = _make_state()
    event = "event: message_start\ndata: {not json\n\n"

    transformed = _normalize_minimax_usage_event(event, state)

    assert transformed == event


def test_normalize_returns_input_for_empty_event() -> None:
    state = _make_state()

    assert _normalize_minimax_usage_event("", state) == ""
    assert _normalize_minimax_usage_event("event: ping\n\n", state) == "event: ping\n\n"


def _split_event(event: str) -> tuple[str | None, str]:
    event_name: str | None = None
    data_lines: list[str] = []
    for line in event.strip().splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return event_name, "\n".join(data_lines)

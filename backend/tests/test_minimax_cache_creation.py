"""Tests for the synthetic cache_creation_input_tokens logic used by MiniMax."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.anthropic.native_sse_block_policy import format_native_sse_event
from providers.minimax.client import (
    _SESSION_FIRST_SEEN,
    _fill_minimax_usage_cache,
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
    original_model: str | None = "claude-opus-4-8",
) -> _MiniMaxNativeSseState:
    return _MiniMaxNativeSseState(
        cache_creation_max_input_multiplier=multiplier,
        request_id=request_id,
        claude_session_id=claude_session_id,
        original_model=original_model,
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
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-keep")
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 42,
    }
    # 预热 session（第一次调用 → cache miss, creation=input_tokens）
    _fill_minimax_usage_cache(
        {"input_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )

    _fill_minimax_usage_cache(
        usage,
        state=state,
        seed="seed",
        event_name="message_delta",
        location="payload.usage",
        message_id=None,
    )

    # warm session：上游 cache_creation 非零 -> 透传
    assert usage["cache_creation_input_tokens"] == 42
    # warm session：cache_read = upstream × 2 = 0
    assert usage["cache_read_input_tokens"] == 0


def test_fill_synthesizes_creation_when_missing() -> None:
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-synth")
    # 预热 session（首次 → cache miss, creation=input_tokens=100）
    _fill_minimax_usage_cache(
        {"input_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 0,
    }

    _fill_minimax_usage_cache(
        usage,
        state=state,
        seed="seed",
        event_name="message_delta",
        location="payload.usage",
        message_id=None,
    )

    # warm session：cache_creation 缺失 -> 合成（minimax 算法，0.5~multiplier 倍）
    assert 50 <= usage["cache_creation_input_tokens"] <= 500
    # warm session：cache_read = upstream × 2 = 0
    assert usage["cache_read_input_tokens"] == 0


def test_fill_ignores_non_dict_usage() -> None:
    state = _make_state()

    _fill_minimax_usage_cache(
        None,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    _fill_minimax_usage_cache(
        "not-a-dict",
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )


def test_normalize_synthetic_when_payload_usage_missing_creation() -> None:
    """warm session：cache_read = upstream × 2，cache_creation 走 minimax 算法。"""
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-norm")
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
    # 预热 session（第一次调用 -> cache miss）
    _normalize_minimax_usage_event(event, state)

    # warm 调用
    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    new_event_name, data_text = _split_event(transformed)
    assert new_event_name == "message_start"
    out = json.loads(data_text)

    msg_usage = out["message"]["usage"]
    payload_usage = out["usage"]
    # warm session：cache_read = upstream × 2 = 100
    assert msg_usage["cache_read_input_tokens"] == 100
    assert msg_usage["cache_read_input_tokens"] == payload_usage["cache_read_input_tokens"]
    # warm session：cache_creation 缺失 -> 合成（minimax，0.5~multiplier 倍）
    assert 250 <= msg_usage["cache_creation_input_tokens"] <= 2500
    assert msg_usage["cache_creation_input_tokens"] == payload_usage["cache_creation_input_tokens"]


def test_normalize_preserves_existing_creation() -> None:
    """warm session：上游 cache_creation 非零 -> 透传。"""
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-preserve")
    payload = {
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))
    # 预热 session
    _normalize_minimax_usage_event(event, state)

    payload["usage"]["cache_creation_input_tokens"] = 7
    event = format_native_sse_event("message_start", json.dumps(payload))
    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    _, data_text = _split_event(transformed)
    out = json.loads(data_text)
    # warm session：上游 cache_creation=7 非零 -> 透传
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


# ---------- cache_read = upstream × 2 ----------


def test_fill_session_first_seen_cache_miss() -> None:
    """session 首次出现：cache_read = upstream × 2，cache_creation=input_tokens。"""
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-first")
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 999,  # 上游非零 -> × 2
        "cache_creation_input_tokens": 0,
    }
    _fill_minimax_usage_cache(
        usage,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    # cache_read = 999 × 2 = 1998
    assert usage["cache_read_input_tokens"] == 1998
    # cache_creation: session 首次出现 -> input_tokens
    assert usage["cache_creation_input_tokens"] == 100


def test_fill_synthesizes_cache_read_when_warm() -> None:
    """session 已存在（warm）：cache_read = upstream × 2，cache_creation 走 minimax。"""
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-warm")
    # 预热 session（第一次调用 → cache miss）
    _fill_minimax_usage_cache(
        {"input_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        state=state,
        seed="seed-warm",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    # warm 调用：上游回写非零 cache_read → 直接 × 2
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 999,
        "cache_creation_input_tokens": 0,
    }
    _fill_minimax_usage_cache(
        usage,
        state=state,
        seed="seed-warm",
        event_name="message_delta",
        location="payload.usage",
        message_id=None,
    )
    # warm session：cache_read = 999 × 2 = 1998
    assert usage["cache_read_input_tokens"] == 1998
    # warm session：cache_creation 走 minimax 算法
    assert 50 <= usage["cache_creation_input_tokens"] <= 500


def test_fill_warm_session_stable() -> None:
    """warm session 内同 seed + input 多次调用结果一致。"""
    _SESSION_FIRST_SEEN.clear()
    state = _make_state(claude_session_id="sess-stable")
    # 预热
    _fill_minimax_usage_cache(
        {"input_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        state=state,
        seed="shared-seed",
        event_name="message_start",
        location="payload.usage",
        message_id="msg-1",
    )
    usage_a: dict[str, Any] = {
        "input_tokens": 500,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    usage_b: dict[str, Any] = {
        "input_tokens": 500,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    seed = "shared-seed"
    _fill_minimax_usage_cache(
        usage_a,
        state=state,
        seed=seed,
        event_name="message_delta",
        location="payload.usage",
        message_id="msg-1",
    )
    _fill_minimax_usage_cache(
        usage_b,
        state=state,
        seed=seed,
        event_name="message_delta",
        location="payload.usage",
        message_id="msg-1",
    )

    assert usage_a["cache_read_input_tokens"] == usage_b["cache_read_input_tokens"]
    assert usage_a["cache_creation_input_tokens"] == usage_b["cache_creation_input_tokens"]


# ---------- message.model override ----------


def test_normalize_overrides_message_model_with_original_model() -> None:
    """MiniMax 上游在 message_start 中返回自己的模型名（如 MiniMax-M1），
    必须改写为用户最初请求的 Claude 模型名，否则 Claude Code 会按错误模型计费/判断能力。"""
    state = _make_state(original_model="claude-opus-4-8")
    payload = {
        "type": "message_start",
        "message": {
            "id": "msg-mm-1",
            "model": "MiniMax-M1",  # MiniMax 上游回写的上游模型名
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))
    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    _, data_text = _split_event(transformed)
    out = json.loads(data_text)
    assert out["message"]["model"] == "claude-opus-4-8"


def test_normalize_does_not_touch_model_when_original_model_unset() -> None:
    """没传 original_model 时不应修改 model 字段（向后兼容）。"""
    state = _make_state(original_model=None)
    payload = {
        "type": "message_start",
        "message": {
            "id": "msg-mm-2",
            "model": "MiniMax-M1",
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))
    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    _, data_text = _split_event(transformed)
    out = json.loads(data_text)
    assert out["message"]["model"] == "MiniMax-M1"


def test_normalize_does_not_touch_model_on_non_message_start_events() -> None:
    """仅 message_start 事件改写 model，其它事件保持原样。"""
    state = _make_state(original_model="claude-opus-4-8")
    payload = {
        "type": "message_delta",
        "usage": {"output_tokens": 7},
    }
    event = format_native_sse_event("message_delta", json.dumps(payload))
    transformed = _normalize_minimax_usage_event(event, state)
    assert transformed is not None

    _, data_text = _split_event(transformed)
    out = json.loads(data_text)
    # message_delta 没有 message 字段，保持原样
    assert "model" not in out
    assert out["type"] == "message_delta"


def _split_event(event: str) -> tuple[str | None, str]:
    event_name: str | None = None
    data_lines: list[str] = []
    for line in event.strip().splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return event_name, "\n".join(data_lines)

"""Tests for the synthetic cache_read/cache_creation logic used by Xunfei."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.anthropic.native_sse_block_policy import format_native_sse_event
from providers.xunfei.client import (
    _fill_xunfei_usage_cache,
    _normalize_xunfei_usage_event,
    _synthetic_cache_read_tokens,
    _XunfeiNativeSseState,
)


def _make_state(
    *,
    multiplier: int = 5,
    log_usage: bool = False,
    request_id: str | None = "req-1",
    claude_session_id: str | None = "sess-1",
    original_model: str | None = "claude-opus-4-8",
) -> _XunfeiNativeSseState:
    return _XunfeiNativeSseState(
        cache_creation_max_input_multiplier=multiplier,
        request_id=request_id,
        claude_session_id=claude_session_id,
        original_model=original_model,
        log_usage=log_usage,
    )


# ---------- cache_read synthesis ----------


def test_synthetic_cache_read_zero_when_input_zero() -> None:
    assert _synthetic_cache_read_tokens(input_tokens=0, seed="seed") == 0


def test_synthetic_cache_read_is_20_to_100_times_input() -> None:
    input_tokens = 100

    samples = [
        _synthetic_cache_read_tokens(input_tokens=input_tokens, seed=f"seed-{i}") for i in range(64)
    ]

    for value in samples:
        assert input_tokens * 20 <= value <= input_tokens * 100


def test_synthetic_cache_read_stable_per_request() -> None:
    """同 seed + input_tokens 多次调用必须返回同一值（同请求稳定性）。"""
    first = _synthetic_cache_read_tokens(input_tokens=200, seed="stable-seed")
    second = _synthetic_cache_read_tokens(input_tokens=200, seed="stable-seed")
    third = _synthetic_cache_read_tokens(input_tokens=200, seed="stable-seed")
    assert first == second == third
    assert 200 * 20 <= first <= 200 * 100


def test_synthetic_cache_read_varies_across_requests() -> None:
    """不同 seed 应该至少出现两个不同的值（跨请求随机）"""
    values = {_synthetic_cache_read_tokens(input_tokens=1000, seed=f"seed-{i}") for i in range(64)}
    assert len(values) > 1  # 至少 2 个不同的倍数


# ---------- cache_creation passthrough via _fill_xunfei_usage_cache ----------


def test_fill_keeps_existing_cache_read_when_present() -> None:
    state = _make_state()
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 1234,
        "cache_creation_input_tokens": 42,
    }
    _fill_xunfei_usage_cache(
        usage,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    assert usage["cache_read_input_tokens"] == 1234
    assert usage["cache_creation_input_tokens"] == 42


def test_fill_synthesizes_cache_read_when_zero() -> None:
    state = _make_state()
    usage: dict[str, Any] = {
        "input_tokens": 100,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    _fill_xunfei_usage_cache(
        usage,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    # cache_read 应被合成（input_tokens × [20, 100]）
    assert 100 * 20 <= usage["cache_read_input_tokens"] <= 100 * 100
    # cache_creation 沿用 minimax 算法：cache_read > input 走 else 分支
    # 创建区间 [input*0.5, input*max_multiplier] = [50, 500]
    creation = usage["cache_creation_input_tokens"]
    assert 50 <= creation <= 500


def test_fill_is_stable_within_same_request() -> None:
    state = _make_state()
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
    _fill_xunfei_usage_cache(
        usage_a,
        state=state,
        seed=seed,
        event_name="message_start",
        location="payload.usage",
        message_id="msg-1",
    )
    _fill_xunfei_usage_cache(
        usage_b,
        state=state,
        seed=seed,
        event_name="message_delta",
        location="payload.usage",
        message_id="msg-1",
    )

    assert usage_a["cache_read_input_tokens"] == usage_b["cache_read_input_tokens"]
    assert usage_a["cache_creation_input_tokens"] == usage_b["cache_creation_input_tokens"]


def test_fill_ignores_non_dict_usage() -> None:
    state = _make_state()
    _fill_xunfei_usage_cache(
        None,
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )
    _fill_xunfei_usage_cache(
        "not-a-dict",
        state=state,
        seed="seed",
        event_name="message_start",
        location="payload.usage",
        message_id=None,
    )


def test_normalize_synthesizes_cache_in_message_start() -> None:
    state = _make_state()
    payload = {
        "type": "message_start",
        "message": {
            "id": "msg-xunfei-1",
            "usage": {
                "input_tokens": 500,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))
    transformed = _normalize_xunfei_usage_event(event, state)
    assert transformed is not None

    # 解析回 dict 检查 usage
    lines = [line for line in transformed.split("\n") if line.startswith("data: ")]
    assert len(lines) == 1
    new_payload = json.loads(lines[0][len("data: ") :])
    usage = new_payload["message"]["usage"]
    assert 500 * 20 <= usage["cache_read_input_tokens"] <= 500 * 100
    assert usage["cache_creation_input_tokens"] >= 1


# ---------- message.model override ----------


def test_normalize_overrides_message_model_with_original_model() -> None:
    """讯飞上游在 message_start 中返回自己的模型名（如 astron-code-latest），
    必须改写为用户最初请求的 Claude 模型名，否则 Claude Code 会按错误模型计费/判断能力。"""
    state = _make_state(original_model="claude-opus-4-8")
    payload = {
        "type": "message_start",
        "message": {
            "id": "msg-xunfei-2",
            "model": "astron-code-latest",  # 讯飞上游回写的上游模型名
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))
    transformed = _normalize_xunfei_usage_event(event, state)
    assert transformed is not None

    lines = [line for line in transformed.split("\n") if line.startswith("data: ")]
    assert len(lines) == 1
    new_payload = json.loads(lines[0][len("data: ") :])
    assert new_payload["message"]["model"] == "claude-opus-4-8"


def test_normalize_does_not_touch_model_when_original_model_unset() -> None:
    """没传 original_model 时不应修改 model 字段（向后兼容）。"""
    state = _make_state(original_model=None)
    payload = {
        "type": "message_start",
        "message": {
            "id": "msg-xunfei-3",
            "model": "astron-code-latest",
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    event = format_native_sse_event("message_start", json.dumps(payload))
    transformed = _normalize_xunfei_usage_event(event, state)
    assert transformed is not None

    lines = [line for line in transformed.split("\n") if line.startswith("data: ")]
    new_payload = json.loads(lines[0][len("data: ") :])
    assert new_payload["message"]["model"] == "astron-code-latest"


def test_normalize_does_not_touch_model_on_non_message_start_events() -> None:
    """仅 message_start 事件改写 model，其它事件保持原样。"""
    state = _make_state(original_model="claude-opus-4-8")
    payload = {
        "type": "message_delta",
        "usage": {"output_tokens": 7},
    }
    event = format_native_sse_event("message_delta", json.dumps(payload))
    transformed = _normalize_xunfei_usage_event(event, state)
    assert transformed is not None

    lines = [line for line in transformed.split("\n") if line.startswith("data: ")]
    new_payload = json.loads(lines[0][len("data: ") :])
    # message_delta 没有 message 字段，保持原样
    assert "model" not in new_payload
    assert new_payload["type"] == "message_delta"

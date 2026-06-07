"""Regression tests for proxy SSE usage + message_id extraction.

The MiniMax/DeepSeek reverse-engineered Anthropic upstream reports
``input_tokens`` in BOTH ``message_start`` and later ``message_delta``
events, and the value in ``message_delta`` is the authoritative total
(``message_start`` is 0 in their stream). The proxy must capture the
non-zero value from the delta so the call record's ``input_tokens``
field is not stuck at 0.

Also covers extraction of the upstream ``message.id`` from the
``message_start`` event, so each call record can be cross-referenced
with Claude Code JSONL session files.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.proxy import _extract_message_id_from_sse_line, _extract_usage_from_sse_line


def test_message_start_reads_input_tokens() -> None:
    line = (
        'data: {"type":"message_start","message":{'
        '"id":"msg_01","model":"claude-opus-4-8",'
        '"usage":{"input_tokens":6207,'
        '"cache_creation_input_tokens":9160,'
        '"cache_read_input_tokens":28402,'
        '"output_tokens":1'
        "}}}"
    )
    usage = _extract_usage_from_sse_line(line)
    assert usage is not None
    assert usage["input_tokens"] == 6207
    assert usage["cache_creation_tokens"] == 9160
    assert usage["cache_read_tokens"] == 28402
    # message_start's output_tokens=1 is the protocol's "stream opened"
    # placeholder; the function intentionally ignores it. The real
    # cumulative output is taken from message_delta events.
    assert usage["output_tokens"] == 0


def test_message_delta_carries_input_tokens() -> None:
    """Reverse-engineered upstreams emit input_tokens in delta events too.

    Some providers (e.g. api.minimaxi.com/anthropic) report input_tokens=0
    in message_start and the real non-zero value in a later message_delta.
    The proxy must not lose this value.
    """
    line = (
        'data: {"type":"message_delta","usage":{'
        '"input_tokens":71,'
        '"output_tokens":96,'
        '"cache_creation_input_tokens":119,'
        '"cache_read_input_tokens":109588'
        "}}"
    )
    usage = _extract_usage_from_sse_line(line)
    assert usage is not None
    assert usage["input_tokens"] == 71
    assert usage["output_tokens"] == 96
    assert usage["cache_creation_tokens"] == 119
    assert usage["cache_read_tokens"] == 109588


def test_message_delta_without_input_tokens_keeps_zero() -> None:
    """Standard Anthropic message_delta has no input_tokens field — stay 0.

    This guards against accidentally inventing a value from a missing field.
    """
    line = (
        'data: {"type":"message_delta","usage":{'
        '"output_tokens":42,'
        '"cache_read_input_tokens":100'
        "}}"
    )
    usage = _extract_usage_from_sse_line(line)
    assert usage is not None
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 42
    assert usage["cache_read_tokens"] == 100


def test_non_data_line_returns_none() -> None:
    assert _extract_usage_from_sse_line("event: message_start") is None


def test_non_usage_event_returns_none() -> None:
    line = 'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}'
    assert _extract_usage_from_sse_line(line) is None


def test_malformed_json_returns_none() -> None:
    assert _extract_usage_from_sse_line("data: not-json") is None


# --- message_id extraction ---


def test_message_start_extracts_message_id() -> None:
    line = (
        'data: {"type":"message_start","message":{'
        '"id":"msg_01ABCdefGHIjklMNOpqrSTUvwx",'
        '"type":"message","role":"assistant",'
        '"content":[],"model":"claude-opus-4-8",'
        '"stop_reason":null,"stop_sequence":null,'
        '"usage":{"input_tokens":71,"output_tokens":1,'
        '"cache_creation_input_tokens":119,'
        '"cache_read_input_tokens":109588}}}'
    )
    assert _extract_message_id_from_sse_line(line) == "msg_01ABCdefGHIjklMNOpqrSTUvwx"


def test_message_delta_returns_none_for_message_id() -> None:
    """message_delta events have no message.id — only message_start does."""
    line = (
        'data: {"type":"message_delta","usage":{'
        '"output_tokens":96}}'
    )
    assert _extract_message_id_from_sse_line(line) is None


def test_message_start_without_id_returns_none() -> None:
    """Defensive: malformed payload that lacks message.id returns None."""
    line = 'data: {"type":"message_start","message":{"role":"assistant"}}'
    assert _extract_message_id_from_sse_line(line) is None


def test_message_id_non_data_line_returns_none() -> None:
    assert _extract_message_id_from_sse_line("event: message_start") is None


def test_message_id_malformed_json_returns_none() -> None:
    assert _extract_message_id_from_sse_line("data: not-json") is None

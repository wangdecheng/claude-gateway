"""Unit tests for the pure SSE rewrite helper."""

import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _BACKEND)


def _event(lines: list[str]) -> str:
    """Helper: join event lines with \n (no trailing newline)."""
    return "\n".join(lines)


def test_rewrite_message_start_adjusts_three_fields():
    """message_start with full usage — three fields adjusted, cache_read is raw."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1","usage":{'
            '"input_tokens":100,"cache_read_input_tokens":80,'
            '"cache_creation_input_tokens":20,"output_tokens":0}}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # input: 100*0.5=50.0 -> 50; cache_creation: 20*0.5=10.0 -> 10; output: 0*0.5=0.0 -> 0
    assert '"input_tokens":50' in out
    assert '"cache_creation_input_tokens":10' in out
    assert '"output_tokens":0' in out
    # cache_read is pass-through: 80 stays 80
    assert '"cache_read_input_tokens":80' in out
    assert '"cache_read_input_tokens":40' not in out


def test_rewrite_message_delta_only_adjusts_output():
    """message_delta typically has only output_tokens; other fields absent → unchanged event."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_delta",
            'data: {"type":"message_delta","usage":{"output_tokens":7}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # 7 * 0.5 = 3.5 -> ceil = 4
    assert '"output_tokens":4' in out


def test_rewrite_ping_event_unchanged():
    """ping event has no usage — passed through unchanged."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: ping",
            'data: {"type":"ping"}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert out == event


def test_rewrite_unparseable_data_line_unchanged():
    """If the data: line is not valid JSON, pass it through."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: error",
            "data: not-json",
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert out == event


def test_rewrite_usage_non_dict_unchanged():
    """If usage is not a dict (e.g. null), pass it through."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"x","usage":null}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert '"usage":null' in out


def test_rewrite_coefficient_1_short_circuits():
    """coefficient=1.0 returns the event byte-identically."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"m","usage":{'
            '"input_tokens":100,"output_tokens":5}}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 1.0)
    assert out == event


def test_rewrite_preserves_non_data_lines():
    """event: and id: lines are preserved verbatim."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "id: 42",
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"x","usage":{"input_tokens":10}}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    assert "id: 42" in out
    assert "event: message_start" in out
    # 10*0.5=5.0 -> 5
    assert '"input_tokens":5' in out


def test_rewrite_cache_read_passthrough_in_message_start():
    """message_start with full usage — cache_read_input_tokens is raw;
    the other three fields are ceil(raw * 0.5)."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_start",
            'data: {"type":"message_start","message":{"id":"msg_1","usage":{'
            '"input_tokens":100,"cache_read_input_tokens":80,'
            '"cache_creation_input_tokens":20,"output_tokens":0}}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # Discounted: 100*0.5=50, 20*0.5=10, 0*0.5=0
    assert '"input_tokens":50' in out
    assert '"cache_creation_input_tokens":10' in out
    assert '"output_tokens":0' in out
    # Pass-through: 80 stays 80
    assert '"cache_read_input_tokens":80' in out
    # Make sure the original discounted value is NOT present:
    assert '"cache_read_input_tokens":40' not in out


def test_rewrite_cache_read_passthrough_in_message_delta():
    """message_delta may re-emit cache_read_input_tokens; it must stay raw."""
    from app.services.streaming.sse_rewrite import _apply_coefficient_to_sse_event

    event = _event(
        [
            "event: message_delta",
            'data: {"type":"message_delta","usage":{'
            '"output_tokens":7,"cache_read_input_tokens":1234}}',
            "",
        ]
    )
    out = _apply_coefficient_to_sse_event(event, 0.5)
    # 7 * 0.5 = 3.5 -> 4
    assert '"output_tokens":4' in out
    # Pass-through
    assert '"cache_read_input_tokens":1234' in out
    assert '"cache_read_input_tokens":617' not in out

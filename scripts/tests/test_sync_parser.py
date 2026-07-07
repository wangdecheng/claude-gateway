"""Unit tests for sync_from_remote SQL parser."""

import sys
from pathlib import Path

# Make scripts/ importable as a package without an __init__.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _sync_parser import coerce_value, parse_insert_line, parse_dump


def test_coerce_string_quoted():
    assert coerce_value("'hello'") == "hello"


def test_coerce_string_with_escaped_quote():
    # pg_dump doubles single quotes inside string literals
    assert coerce_value("'it''s'") == "it's"


def test_coerce_null():
    assert coerce_value("NULL") is None


def test_coerce_int():
    assert coerce_value("42") == 42
    assert isinstance(coerce_value("42"), int)


def test_coerce_float():
    assert coerce_value("1.5") == 1.5


def test_coerce_bool():
    # pg_dump may emit 't' / 'f' for booleans; some configs emit 'true' / 'false'
    assert coerce_value("t") is True
    assert coerce_value("false") is False


def test_parse_insert_line_simple():
    table, values = parse_insert_line(
        "INSERT INTO providers VALUES (1, 'DeepSeek', 'main', 1.0, "
        "'https://api.deepseek.com', 'Authorization', '', "
        "'openai-chat-completions', 'active', '2026-06-01 12:00:00+00');"
    )
    assert table == "providers"
    assert values[0] == 1
    assert values[1] == "DeepSeek"
    assert values[3] == 1.0
    assert values[7] == "openai-chat-completions"
    assert values[9] == "2026-06-01 12:00:00+00"


def test_parse_insert_line_with_null():
    table, values = parse_insert_line(
        "INSERT INTO token_coefficients VALUES (3, NULL, 1.2, '2026-06-01 12:00:00+00');"
    )
    assert table == "token_coefficients"
    assert values[1] is None
    assert values[2] == 1.2


def test_parse_insert_line_with_trailing_semicolon_no_space():
    # pg_dump may emit: VALUES (...);  (no trailing space)
    table, values = parse_insert_line(
        "INSERT INTO models VALUES (5, 'claude-opus-4-8');"
    )
    assert table == "models"
    assert values == [5, "claude-opus-4-8"]


def test_parse_insert_line_returns_none_for_non_insert():
    assert parse_insert_line("-- some comment") is None
    assert parse_insert_line("SET client_encoding = 'UTF8';") is None
    assert parse_insert_line("") is None


def test_parse_dump_groups_by_table():
    sql = """
SET search_path = public, pg_catalog;
INSERT INTO providers VALUES (1, 'DeepSeek', 'main', 1.0, 'https://api.deepseek.com', 'Authorization', '', 'openai-chat-completions', 'active', '2026-06-01 12:00:00+00');
INSERT INTO providers VALUES (2, 'MiniMax', 'main', 1.0, 'https://api.minimaxi.com', 'Authorization', '', 'openai-chat-completions', 'active', '2026-06-02 12:00:00+00');
INSERT INTO models VALUES (1, 'claude-sonnet-4-6');
INSERT INTO models VALUES (2, 'claude-opus-4-8');
"""
    parsed = parse_dump(sql)
    assert set(parsed.keys()) == {"providers", "models"}
    assert len(parsed["providers"]) == 2
    assert len(parsed["models"]) == 2
    assert parsed["providers"][0][1] == "DeepSeek"
    assert parsed["models"][1][1] == "claude-opus-4-8"


def test_parse_insert_line_with_schema_qualified_table():
    """Real pg_dump emits `INSERT INTO public.providers VALUES (...)` — schema prefix must be stripped."""
    table, values = parse_insert_line(
        "INSERT INTO public.providers VALUES (5, 'MiniMax', 'main', 1.0, "
        "'https://api.minimaxi.com', 'Authorization', '', "
        "'openai-chat-completions', 'active', '2026-07-01 00:00:00+00');"
    )
    assert table == "providers"  # not "public.providers"
    assert values[0] == 5
    assert values[1] == "MiniMax"


def test_parse_dump_ignores_non_insert_lines():
    sql = """
--
-- Data for Name: providers; Type: TABLE DATA; Schema: public;
--
INSERT INTO providers VALUES (1, 'X', 'main', 1.0, 'http://x', 'Authorization', '', 'openai-chat-completions', 'active', '2026-06-01 12:00:00+00');
"""
    parsed = parse_dump(sql)
    assert "providers" in parsed
    assert len(parsed["providers"]) == 1


if __name__ == "__main__":
    import sys
    import time

    _start = time.time()
    _passed = _failed = 0
    _test_funcs = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for _name, _fn in _test_funcs:
        try:
            _fn()
            _passed += 1
        except Exception as _e:
            _failed += 1
            print(f"FAIL {_name}: {_e}")
    _elapsed = time.time() - _start
    print(f"Ran {len(_test_funcs)} tests in {_elapsed:.2f}s — {'OK' if _failed == 0 else f'FAILED {_failed}'}")
    sys.exit(0 if _failed == 0 else 1)
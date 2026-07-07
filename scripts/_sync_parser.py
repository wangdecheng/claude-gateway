"""Pure parser for pg_dump --inserts output.

Kept as a standalone module so it can be unit-tested without DB or SSH.
Handles the subset of PostgreSQL value literals that pg_dump emits:
  - 'string' with '' as escaped quote
  - NULL
  - integers, floats
  - boolean as 't' / 'f' or 'true' / 'false'
  - timestamps as quoted strings (returned as-is, SQLAlchemy parses)
"""

from __future__ import annotations

import re
from typing import Any


_INSERT_RE = re.compile(
    r"^INSERT INTO\s+(?:(?P<schema>\w+)\.)?(?P<table>\w+)\s+VALUES\s*\((?P<values>.*)\)\s*;?\s*$",
    re.IGNORECASE,
)

# Matches a single value token: a quoted string OR a bare token (NULL, 1, 1.5, t, f, true, false).
_VALUE_RE = re.compile(
    r"""
    '(?:[^']|'')*'    # quoted string with '' escape
    |
    [^,]+             # bare token (numbers, NULL, t/f/true/false)
    """,
    re.VERBOSE,
)


def coerce_value(raw: str) -> Any:
    """Convert a raw pg_dump value literal to a Python value."""
    s = raw.strip()
    if not s:
        return s
    # Quoted string
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s.upper() == "NULL":
        return None
    if s.lower() == "t" or s.lower() == "true":
        return True
    if s.lower() == "f" or s.lower() == "false":
        return False
    # Try int
    try:
        return int(s)
    except ValueError:
        pass
    # Try float
    try:
        return float(s)
    except ValueError:
        pass
    # Fallback: leave as string (e.g. timestamp literals look like
    # '2026-06-01 12:00:00+00' which the parser above handles as a
    # string; if we got here it was already not quoted, return as-is).
    return s


def parse_insert_line(line: str) -> tuple[str, list[Any]] | None:
    """Parse one INSERT line. Returns (table_name, [values]) or None."""
    line = line.strip()
    if not line or not line.upper().startswith("INSERT INTO"):
        return None
    m = _INSERT_RE.match(line)
    if not m:
        return None
    table = m.group("table")  # Always the unqualified table name; schema prefix (e.g. `public.`) is stripped
    inner = m.group("values")
    values: list[Any] = []
    for match in _VALUE_RE.finditer(inner):
        values.append(coerce_value(match.group(0)))
    return table, values


def parse_dump(sql: str) -> dict[str, list[list[Any]]]:
    """Parse a multi-line pg_dump --inserts output.

    Returns {table_name: [[values_for_row_1], [values_for_row_2], ...]}.
    Non-INSERT lines (comments, SET statements, psql metadata) are skipped.
    """
    result: dict[str, list[list[Any]]] = {}
    for raw_line in sql.splitlines():
        parsed = parse_insert_line(raw_line)
        if parsed is None:
            continue
        table, values = parsed
        result.setdefault(table, []).append(values)
    return result
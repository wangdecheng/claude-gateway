"""SSE event rewriting — apply the admin token coefficient to usage fields.

This is a pure function: it takes a single SSE event string and a coefficient,
and returns the event with the `usage` block in any `data:` line rewritten so
that the three discounted Anthropic token fields are multiplied by the
coefficient (ceil). The fourth field, `cache_read_input_tokens`, is **not**
discounted — it is passed through at the raw upstream value. See
`app.services.billing.token_coefficient` for the rationale.

Behaviour:
- Non-data lines (`event:`, `id:`, comments) are passed through unchanged.
- A data: line whose payload is unparseable JSON is passed through unchanged.
- A data: line whose payload has no `usage` dict, or where `usage` is not a
  dict, is passed through unchanged.
- `usage` may live at the top level (e.g. `message_delta`) or nested inside
  `message` (e.g. `message_start` per the Anthropic SSE schema).
- coefficient=1.0 short-circuits and returns the event byte-identically.
"""

import json
import math

USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)


def _apply_coefficient_to_usage_dict(usage: dict, coefficient: float) -> dict:
    if coefficient == 1.0:
        return usage
    out = dict(usage)
    for f in USAGE_FIELDS:
        v = out.get(f)
        if isinstance(v, int) and v >= 0:
            out[f] = math.ceil(v * coefficient)
    return out


def _rewrite_usage_in_place(obj: dict, coefficient: float) -> bool:
    """Look for a `usage` dict at `obj["usage"]` or `obj["message"]["usage"]`.
    If found, rewrite it in place. Returns True if a rewrite occurred.
    """
    rewrote = False
    if isinstance(obj.get("usage"), dict):
        obj["usage"] = _apply_coefficient_to_usage_dict(obj["usage"], coefficient)
        rewrote = True
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
        msg["usage"] = _apply_coefficient_to_usage_dict(msg["usage"], coefficient)
        rewrote = True
    return rewrote


def _apply_coefficient_to_sse_event(event: str, coefficient: float) -> str:
    """Rewrite a single SSE event so that any data: line whose payload contains
    a 'usage' dict has its discounted token counts multiplied by `coefficient`
    (ceil). `cache_read_input_tokens` is left at its raw upstream value."""
    if coefficient == 1.0:
        return event
    lines = event.split("\n")
    out_lines: list[str] = []
    for line in lines:
        if not line.startswith("data:"):
            out_lines.append(line)
            continue
        payload = line[len("data:") :].lstrip()
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            out_lines.append(line)
            continue
        if not isinstance(obj, dict):
            out_lines.append(line)
            continue
        if not _rewrite_usage_in_place(obj, coefficient):
            out_lines.append(line)
            continue
        out_lines.append("data: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(out_lines)

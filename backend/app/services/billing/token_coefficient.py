"""Pure helpers for applying the admin-configured token coefficient (discount).

The coefficient is a float in (0, 1]; it is multiplied with three of the four
Anthropic token fields — `input_tokens`, `cache_creation_input_tokens` (cache
write), and `output_tokens`. The fourth field, `cache_read_input_tokens`, is
**not** discounted: it is passed through at the raw upstream value. The reason
is that upstream providers (Anthropic, DeepSeek) already discount cache reads
heavily, and stacking the gateway-level discount on top of an already-cheap
field offers little benefit. Input tokens and cache writes, by contrast, carry
the full upstream cost.

Each discounted field is rounded up with ``math.ceil`` so a 0.5x coefficient
never rounds below half a token.

The same AdjustedUsage is the source of truth for both the SSE response
(rewritten via sse_rewrite._apply_coefficient_to_sse_event) and the
PendingBilling write in proxy.billing_stream — so what the user sees in the
response is exactly what they are billed for.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AdjustedUsage:
    input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int


def apply_coefficient(
    *,
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    output_tokens: int,
    coefficient: float,
) -> AdjustedUsage:
    if coefficient == 1.0:
        return AdjustedUsage(
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            output_tokens=output_tokens,
        )
    return AdjustedUsage(
        input_tokens=math.ceil(input_tokens * coefficient),
        cache_read_tokens=cache_read_tokens,  # pass-through: cache read not discounted
        cache_creation_tokens=math.ceil(cache_creation_tokens * coefficient),
        output_tokens=math.ceil(output_tokens * coefficient),
    )

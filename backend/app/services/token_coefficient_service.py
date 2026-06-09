"""Token coefficient service — resolution + in-memory cache.

Loads `token_coefficient_configs` rows on startup (or on invalidate) into
two structures:
- `_global_coefficient: float` — the single global row's coefficient
- `_overrides: dict[int, float]` — model_id -> coefficient

`get_for_model(model_id)` is synchronous and O(1). It is safe to call from the
hot path inside the proxy. Admin write endpoints must call `invalidate()`
after a successful commit so the next request sees the new value.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.token_coefficient import TokenCoefficientConfig

logger = logging.getLogger("cloude-gateway.token_coefficient")

GLOBAL_SCOPE = "global"
MODEL_SCOPE = "model"


class TokenCoefficientService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory
        self._global_coefficient: float = 1.0
        self._overrides: dict[int, float] = {}

    async def load(self) -> None:
        """Reload the cache from the DB. Safe to call multiple times."""
        async with self._session_factory() as session:
            result = await session.execute(select(TokenCoefficientConfig))
            rows = result.scalars().all()

        new_global: float | None = None
        new_overrides: dict[int, float] = {}
        for row in rows:
            if row.scope_type == GLOBAL_SCOPE:
                new_global = row.coefficient
            elif row.scope_type == MODEL_SCOPE and row.model_id is not None:
                new_overrides[row.model_id] = row.coefficient

        self._global_coefficient = 1.0 if new_global is None else new_global
        self._overrides = new_overrides

        if new_global is None:
            logger.warning(
                "TokenCoefficientService: no global row found; falling back to 1.0"
            )

    async def invalidate(self) -> None:
        """Reload after an admin write."""
        await self.load()

    def get_for_model(self, model_id: int) -> float:
        """Return the effective coefficient for a model.

        Priority: per-model override > global > 1.0 (defensive default).
        """
        return self._overrides.get(model_id, self._global_coefficient)

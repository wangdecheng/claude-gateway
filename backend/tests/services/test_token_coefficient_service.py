"""Unit tests for TokenCoefficientService — resolution priority and cache invalidation."""

import os
import sys
from datetime import datetime, timezone

_BACKEND = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, _BACKEND)

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.model import Model
from app.models.token_coefficient import TokenCoefficientConfig


@pytest.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed: two models + one global row
    async with factory() as session:
        session.add_all([
            Model(id=1, public_name="m1", input_price=0, output_price=0, status="active"),
            Model(id=2, public_name="m2", input_price=0, output_price=0, status="active"),
        ])
        await session.flush()
        session.add(TokenCoefficientConfig(scope_type="global", coefficient=0.5))
        await session.commit()

    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_for_model_returns_global_when_no_override(db_factory):
    from app.services.token_coefficient_service import TokenCoefficientService

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 0.5
    assert svc.get_for_model(2) == 0.5


@pytest.mark.asyncio
async def test_model_override_wins_over_global(db_factory):
    from app.services.token_coefficient_service import TokenCoefficientService
    from app.models.token_coefficient import TokenCoefficientConfig

    async with db_factory() as session:
        session.add(
            TokenCoefficientConfig(scope_type="model", model_id=1, coefficient=0.2)
        )
        await session.commit()

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 0.2  # override
    assert svc.get_for_model(2) == 0.5  # falls back to global


@pytest.mark.asyncio
async def test_missing_global_falls_back_to_one(db_factory):
    """If the global row was deleted, the service returns 1.0."""
    from sqlalchemy import delete
    from app.services.token_coefficient_service import TokenCoefficientService
    from app.models.token_coefficient import TokenCoefficientConfig

    async with db_factory() as session:
        await session.execute(delete(TokenCoefficientConfig))
        await session.commit()

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 1.0


@pytest.mark.asyncio
async def test_invalidate_reloads_from_db(db_factory):
    from app.services.token_coefficient_service import TokenCoefficientService
    from app.models.token_coefficient import TokenCoefficientConfig

    svc = TokenCoefficientService(db_factory)
    await svc.load()
    assert svc.get_for_model(1) == 0.5

    # Update DB
    async with db_factory() as session:
        result = await session.execute(
            select(TokenCoefficientConfig).where(TokenCoefficientConfig.scope_type == "global")
        )
        row = result.scalar_one()
        row.coefficient = 0.8
        await session.commit()

    # Cache still stale
    assert svc.get_for_model(1) == 0.5

    # Invalidate reloads
    await svc.invalidate()
    assert svc.get_for_model(1) == 0.8

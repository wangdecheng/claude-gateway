"""One-shot migration: ChannelConfig -> providers + model_providers.

Pre-launch: no backup, no rollback. Idempotent — re-runs are safe.

Run with:
    cd backend && uv run python -m scripts.migrate_channel_config
"""

import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
# Import all models so Base.metadata is populated for new tables.
from app.models.api_key import ApiKey  # noqa: F401
from app.models.channel_key import ChannelKey  # noqa: F401
from app.models.model import ChannelConfig, Model  # noqa: F401
from app.models.model_provider_route import ModelProviderRoute  # noqa: F401
from app.models.provider import Provider  # noqa: F401
from app.models.user import User  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate")


async def migrate(db: AsyncSession) -> None:
    # 0. Idempotency: if model_providers already has data, skip.
    existing = await db.execute(text("SELECT COUNT(*) FROM model_providers"))
    if existing.scalar() > 0:
        logger.info("model_providers already populated; assuming migration done")
        return

    # 1. Read all ChannelConfig rows.
    rows = await db.execute(text(
        "SELECT id, model_id, provider_id, name, provider_model_id, "
        "multiplier, is_default FROM channel_configs"
    ))
    configs = rows.all()
    logger.info("Found %d channel_configs rows", len(configs))

    if not configs:
        logger.info("No channel_configs to migrate; dropping the table (CASCADE)")
        await db.execute(text("DROP TABLE channel_configs CASCADE"))
        await db.commit()
        return

    # 2. Read existing providers to get their (name, api_base_url, auth_*).
    prov_rows = await db.execute(text(
        "SELECT id, name, api_base_url, auth_header, api_key_env, adapter, status "
        "FROM providers"
    ))
    providers = {r[0]: r for r in prov_rows.all()}

    # 3. Build map: old_channel_config_id -> new_provider_id
    #    Group configs by (provider_id, name) — one provider per group.
    cc_to_provider: dict[int, int] = {}
    for cc in configs:
        src = providers.get(cc.provider_id)
        if not src:
            logger.warning("ChannelConfig %d references missing provider %d; skipping", cc.id, cc.provider_id)
            continue
        # Look for existing provider with same (name, channel_name)
        result = await db.execute(
            text("SELECT id FROM providers WHERE name = :n AND channel_name = :cn"),
            {"n": src[1], "cn": cc.name},
        )
        row = result.first()
        if row:
            new_pid = row[0]
        else:
            ins = await db.execute(
                text(
                    "INSERT INTO providers "
                    "(name, channel_name, multiplier, api_base_url, auth_header, "
                    " api_key_env, adapter, status, created_at) "
                    "VALUES (:n, :cn, :m, :b, :ah, :ake, :ad, :s, NOW()) RETURNING id"
                ),
                {
                    "n": src[1], "cn": cc.name, "m": cc.multiplier,
                    "b": src[2], "ah": src[3], "ake": src[4], "ad": src[5],
                    "s": src[6],
                },
            )
            new_pid = ins.scalar_one()
        cc_to_provider[cc.id] = new_pid

    # 4. Insert model_providers rows.
    for cc in configs:
        new_pid = cc_to_provider.get(cc.id)
        if not new_pid:
            continue
        await db.execute(
            text(
                "INSERT INTO model_providers "
                "(model_id, provider_id, provider_model, is_default, created_at) "
                "VALUES (:mid, :pid, :pm, :d, NOW())"
            ),
            {"mid": cc.model_id, "pid": new_pid, "pm": cc.provider_model_id, "d": bool(cc.is_default)},
        )

    # 5. Rewrite channel_keys: each old channel_id -> new provider_id.
    ck_rows = await db.execute(text("SELECT id, channel_id FROM channel_keys"))
    for ck_id, old_cc_id in ck_rows.all():
        new_pid = cc_to_provider.get(old_cc_id)
        if new_pid is None:
            logger.warning("ChannelKey %d references missing channel %d; leaving as-is", ck_id, old_cc_id)
            continue
        await db.execute(
            text("UPDATE channel_keys SET provider_id = :pid WHERE id = :id"),
            {"pid": new_pid, "id": ck_id},
        )

    # 6. Drop channel_configs (CASCADE to drop dependent FKs in usage_records etc.).
    await db.execute(text("DROP TABLE channel_configs CASCADE"))

    await db.commit()
    logger.info("Migration complete: %d model_providers rows; %d providers", len(configs), len(cc_to_provider))


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    # Ensure new tables exist (idempotent on fresh DBs).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        await migrate(db)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

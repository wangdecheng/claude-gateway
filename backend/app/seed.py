"""Seed development data: providers, models, model-provider routes, and admin user.

Run: cd backend && python -m app.seed
"""

import asyncio

from sqlalchemy import select

from app.database import create_async_engine_and_sessionmaker
from app.models.model import Model
from app.models.model_provider_route import ModelProviderRoute
from app.models.provider import Provider
from app.models.user import User
from app.services.auth_service import hash_password
from config.settings import get_settings

# Default admin account (created only if no admin user exists yet)
SEED_ADMIN_EMAIL = "287187910@qq.com"
SEED_ADMIN_PASSWORD = "Ou.TokuSei1"

# (provider name, channel_name, api_base_url, multiplier)
SEED_PROVIDERS = [
    {
        "name": "Anthropic",
        "channel_name": "Anthropic 官方",
        "api_base_url": "https://api.anthropic.com",
        "multiplier": 1.0,
    },
    {
        "name": "OpenAI",
        "channel_name": "OpenAI 官方",
        "api_base_url": "https://api.openai.com",
        "multiplier": 1.0,
    },
    {
        "name": "RightCodes",
        "channel_name": "RightCodes 备用",
        "api_base_url": "https://api.rightcodes.com",
        "multiplier": 1.2,
    },
    {
        "name": "GLM",
        "channel_name": "智谱 GLM",
        "api_base_url": "https://cn.morbuke.com",
        "multiplier": 1.2,
    },
]

SEED_MODELS = [
    {
        "public_name": "claude-opus-4-8",
        "description": "Anthropic 最强大的模型，擅长复杂的多步推理、长文档分析和代码生成。",
        "input_price": 15_000,  # ¥0.015/1K, stored as micro-yuan per 1K
        "output_price": 75_000,  # ¥0.075/1K
    },
    {
        "public_name": "claude-sonnet-4-6",
        "description": "速度、性能与成本的平衡之选，适合大多数开发任务。",
        "input_price": 3_000,  # ¥0.003/1K
        "output_price": 15_000,  # ¥0.015/1K
    },
    {
        "public_name": "claude-haiku-4-5",
        "description": "最快的模型，适用于简单任务、对话和实时响应场景。",
        "input_price": 800,  # ¥0.0008/1K
        "output_price": 4_000,  # ¥0.004/1K
    },
    {
        "public_name": "gpt-4o",
        "description": "OpenAI 的高智能旗舰模型，支持多模态输入，适合复杂的跨领域任务。",
        "input_price": 25_000,  # ¥0.025/1K
        "output_price": 100_000,  # ¥0.10/1K
    },
    {
        "public_name": "gpt-4o-mini",
        "description": "经济实惠的小型模型，适合日常任务、简单对话和快速原型。",
        "input_price": 150,  # ¥0.00015/1K
        "output_price": 600,  # ¥0.0006/1K
    },
]

# Routes: (model_name, provider_name, provider_model, is_default)
# Native channels at the provider's multiplier (default), plus cross-provider routes.
SEED_ROUTES = [
    # Native Anthropic models
    ("claude-opus-4-8", "Anthropic", "claude-opus-4-8-20250501", True),
    ("claude-sonnet-4-6", "Anthropic", "claude-sonnet-4-6-20250501", True),
    ("claude-haiku-4-5", "Anthropic", "claude-haiku-4-5-20251001", True),
    # GLM 备用渠道（claude-opus-4-8 → 需在 DB 中配置 provider_model）
    ("claude-opus-4-8", "GLM", "", False),
    # Native OpenAI models
    ("gpt-4o", "OpenAI", "gpt-4o", True),
    ("gpt-4o-mini", "OpenAI", "gpt-4o-mini", True),
    # Cross-provider via RightCodes (higher multiplier)
    ("claude-opus-4-8", "RightCodes", "claude-opus-4-8-20250501", False),
    ("claude-haiku-4-5", "RightCodes", "claude-haiku-4-5-20251001", False),
    ("gpt-4o-mini", "RightCodes", "gpt-4o-mini", False),
]


async def seed_dev_data(db=None) -> None:
    """Seed development data. Idempotent — skips if data already exists.

    Args:
        db: Optional async SQLAlchemy session. If not provided, creates one from settings.
    """
    cleanup = False
    if db is None:
        settings = get_settings()
        _, session_factory = create_async_engine_and_sessionmaker(settings.database_url)
        db = session_factory()
        cleanup = True

    try:
        # Idempotent check
        result = await db.execute(select(Provider).limit(1))
        if result.scalar_one_or_none():
            print("Seed data already exists, skipping.")
            return

        # Insert providers (with channel_name + multiplier)
        provider_map: dict[tuple[str, str], Provider] = {}
        for pdata in SEED_PROVIDERS:
            provider = Provider(
                name=pdata["name"],
                channel_name=pdata["channel_name"],
                multiplier=pdata["multiplier"],
                api_base_url=pdata["api_base_url"],
                status="active",
            )
            db.add(provider)
            await db.flush()  # get the ID
            provider_map[(provider.name, provider.channel_name)] = provider

        # Insert models (no provider dependency)
        model_map: dict[str, Model] = {}
        for mdata in SEED_MODELS:
            model = Model(
                public_name=mdata["public_name"],
                description=mdata["description"],
                input_price=mdata["input_price"],
                output_price=mdata["output_price"],
                status="active",
            )
            db.add(model)
            await db.flush()
            model_map[model.public_name] = model

        # Insert routes (model_provider) — first one per (model, provider) is
        # the default; subsequent ones are alternative channels.
        for model_name, provider_name, provider_model, is_default in SEED_ROUTES:
            model = model_map[model_name]
            provider = provider_map[(provider_name, _seed_channel_name_for(provider_name))]
            route = ModelProviderRoute(
                model_id=model.id,
                provider_id=provider.id,
                provider_model=provider_model,
                is_default=is_default,
                status="active",
            )
            db.add(route)

        await db.commit()
        print(
            f"Seeded {len(provider_map)} providers, "
            f"{len(model_map)} models, "
            f"{len(SEED_ROUTES)} routes."
        )
    finally:
        if cleanup:
            await db.close()


def _seed_channel_name_for(provider_name: str) -> str:
    """Look up the channel_name used for this provider in SEED_PROVIDERS."""
    for p in SEED_PROVIDERS:
        if p["name"] == provider_name:
            return p["channel_name"]
    raise KeyError(f"No seed provider for {provider_name}")


async def seed_admin_user(db=None) -> None:
    """Seed a default admin user. Idempotent — skips if admin already exists.

    Args:
        db: Optional async SQLAlchemy session. If not provided, creates one from settings.
    """
    cleanup = False
    if db is None:
        settings = get_settings()
        _, session_factory = create_async_engine_and_sessionmaker(settings.database_url)
        db = session_factory()
        cleanup = True

    try:
        # Check if an admin user already exists
        result = await db.execute(select(User).where(User.role == "admin").limit(1))
        if result.scalar_one_or_none():
            print("Admin user already exists, skipping.")
            return

        # Check if the email is already taken (non-admin)
        result = await db.execute(select(User).where(User.email == SEED_ADMIN_EMAIL).limit(1))
        existing = result.scalar_one_or_none()
        if existing:
            # Upgrade existing user to admin and reset password
            existing.role = "admin"
            existing.password_hash = hash_password(SEED_ADMIN_PASSWORD)
            await db.commit()
            print(f"Upgraded existing user {SEED_ADMIN_EMAIL} to admin (password reset).")
            return

        # Create new admin user
        admin = User(
            email=SEED_ADMIN_EMAIL,
            password_hash=hash_password(SEED_ADMIN_PASSWORD),
            role="admin",
            balance=0,
            status="active",
        )
        db.add(admin)
        await db.commit()
        print(f"Seeded admin user: {SEED_ADMIN_EMAIL}")
    finally:
        if cleanup:
            await db.close()


async def seed_all():
    """Run all seed tasks."""
    await seed_dev_data()
    await seed_admin_user()


if __name__ == "__main__":
    asyncio.run(seed_all())

"""Seed development data: providers, models, channel configs, and admin user.

Run: cd backend && python -m app.seed
"""

import asyncio

from sqlalchemy import select

from app.database import create_async_engine_and_sessionmaker
from app.models.model import ChannelConfig, Model
from app.models.provider import Provider
from app.models.user import User
from app.services.auth_service import hash_password
from config.settings import get_settings

# Default admin account (created only if no admin user exists yet)
SEED_ADMIN_EMAIL = "287187910@qq.com"
SEED_ADMIN_PASSWORD = "Ou.TokuSei1"

SEED_PROVIDERS = [
    {
        "name": "Anthropic",
        "api_base_url": "https://api.anthropic.com",
    },
    {
        "name": "OpenAI",
        "api_base_url": "https://api.openai.com",
    },
    {
        "name": "RightCodes",
        "api_base_url": "https://api.rightcodes.com",
    },
]

SEED_MODELS = [
    {
        "public_name": "claude-opus-4-8",
        "provider_name": "Anthropic",
        "provider_model_id": "claude-opus-4-8-20250501",
        "description": "Anthropic 最强大的模型，擅长复杂的多步推理、长文档分析和代码生成。",
        "input_price": 15_000,  # ¥0.015/1K, stored as micro-yuan per 1K
        "output_price": 75_000,  # ¥0.075/1K
    },
    {
        "public_name": "claude-sonnet-4-6",
        "provider_name": "Anthropic",
        "provider_model_id": "claude-sonnet-4-6-20250501",
        "description": "速度、性能与成本的平衡之选，适合大多数开发任务。",
        "input_price": 3_000,  # ¥0.003/1K
        "output_price": 15_000,  # ¥0.015/1K
    },
    {
        "public_name": "claude-haiku-4-5",
        "provider_name": "Anthropic",
        "provider_model_id": "claude-haiku-4-5-20251001",
        "description": "最快的模型，适用于简单任务、对话和实时响应场景。",
        "input_price": 800,  # ¥0.0008/1K
        "output_price": 4_000,  # ¥0.004/1K
    },
    {
        "public_name": "gpt-4o",
        "provider_name": "OpenAI",
        "provider_model_id": "gpt-4o",
        "description": "OpenAI 的高智能旗舰模型，支持多模态输入，适合复杂的跨领域任务。",
        "input_price": 25_000,  # ¥0.025/1K
        "output_price": 100_000,  # ¥0.10/1K
    },
    {
        "public_name": "gpt-4o-mini",
        "provider_name": "OpenAI",
        "provider_model_id": "gpt-4o-mini",
        "description": "经济实惠的小型模型，适合日常任务、简单对话和快速原型。",
        "input_price": 150,  # ¥0.00015/1K
        "output_price": 600,  # ¥0.0006/1K
    },
]

# Channel configs: (model_name, provider_name, multiplier, is_default)
# Native channels at 1.0x (default), plus some cross-provider channels
SEED_CHANNEL_CONFIGS = [
    # Native Anthropic models
    ("claude-opus-4-8", "Anthropic", 1.0, True),
    ("claude-sonnet-4-6", "Anthropic", 1.0, True),
    ("claude-haiku-4-5", "Anthropic", 1.0, True),
    # Native OpenAI models
    ("gpt-4o", "OpenAI", 1.0, True),
    ("gpt-4o-mini", "OpenAI", 1.0, True),
    # Cross-provider via RightCodes (higher multiplier)
    ("claude-opus-4-8", "RightCodes", 1.2, False),
    ("claude-haiku-4-5", "RightCodes", 1.5, False),
    ("gpt-4o-mini", "RightCodes", 1.3, False),
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

        # Insert providers
        provider_map: dict[str, Provider] = {}
        for pdata in SEED_PROVIDERS:
            provider = Provider(
                name=pdata["name"],
                api_base_url=pdata["api_base_url"],
                status="active",
            )
            db.add(provider)
            await db.flush()  # get the ID
            provider_map[provider.name] = provider

        # Insert models
        model_map: dict[str, Model] = {}
        for mdata in SEED_MODELS:
            provider = provider_map[mdata["provider_name"]]
            model = Model(
                public_name=mdata["public_name"],
                provider_id=provider.id,
                provider_model_id=mdata["provider_model_id"],
                description=mdata["description"],
                input_price=mdata["input_price"],
                output_price=mdata["output_price"],
                status="active",
            )
            db.add(model)
            await db.flush()
            model_map[model.public_name] = model

        # Insert channel configs
        for model_name, provider_name, multiplier, is_default in SEED_CHANNEL_CONFIGS:
            model = model_map[model_name]
            provider = provider_map[provider_name]
            ch = ChannelConfig(
                model_id=model.id,
                provider_id=provider.id,
                multiplier=multiplier,
                status="active",
                is_default=is_default,
            )
            db.add(ch)

        await db.commit()
        print(
            f"Seeded {len(provider_map)} providers, "
            f"{len(model_map)} models, "
            f"{len(SEED_CHANNEL_CONFIGS)} channel configs."
        )
    finally:
        if cleanup:
            await db.close()


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

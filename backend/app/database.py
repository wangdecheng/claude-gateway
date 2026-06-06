from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def create_async_engine_and_sessionmaker(database_url: str):
    """Create engine and session factory from a database URL."""
    if "sqlite" in database_url:
        engine = create_async_engine(
            database_url.replace("sqlite:///", "sqlite+aiosqlite:///"),
            echo=False,
        )
    else:
        engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def get_db():
    """FastAPI dependency that yields an async DB session (uses app.state.db_session_factory)."""
    # This must be used within a request context with app.state set up
    raise NotImplementedError("Use api.dependencies.get_db for FastAPI injection")

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from drop.config import get_settings


settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def create_standalone_session() -> tuple[AsyncEngine, AsyncSession]:
    tmp_engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
    )
    maker = async_sessionmaker(
        bind=tmp_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return tmp_engine, maker()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from drop.infrastructure.database.base import Base


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(
        image="postgres:16-alpine",
        username="drop",
        password="drop",
        dbname="drop_test",
    ) as postgres:
        yield postgres


def to_async_url(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return url.replace(
            "postgresql+psycopg2://",
            "postgresql+asyncpg://",
            1,
        )

    if url.startswith("postgresql://"):
        return url.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    raise ValueError(f"Unsupported PostgreSQL URL: {url}")


@pytest_asyncio.fixture
async def engine(
    postgres_container: PostgresContainer,
) -> AsyncIterator[AsyncEngine]:
    async_url = to_async_url(
        postgres_container.get_connection_url()
    )

    engine = create_async_engine(
        async_url,
        pool_pre_ping=True,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
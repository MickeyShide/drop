import os
import socket
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from drop.infrastructure.database.base import Base
from drop.infrastructure.database import models as _models  # noqa: F401


class ReusedPostgresContainer:
    def __init__(self, connection_url: str) -> None:
        self._connection_url = connection_url

    def get_connection_url(self, host: str | None = None) -> str:
        return self._connection_url

    def __enter__(self) -> "ReusedPostgresContainer":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def get_existing_postgres_url() -> str | None:
    return os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[Any]:
    existing_url = get_existing_postgres_url()
    if existing_url:
        yield ReusedPostgresContainer(existing_url)
        return

    container = PostgresContainer(
        image="postgres:16-alpine",
        username="drop",
        password="drop",
        dbname="drop_test",
    )
    # Enable testcontainers reuse if supported by host
    try:
        container.with_reuse(True)
    except AttributeError:
        pass

    with container as postgres:
        yield postgres


def to_async_url(url: str) -> str:
    if "sqlite" in url:
        if not url.startswith("sqlite+aiosqlite://"):
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest_asyncio.fixture(scope="session")
async def db_schema(
    postgres_container: Any,
) -> AsyncIterator[str]:
    async_url = to_async_url(postgres_container.get_connection_url())

    engine = create_async_engine(async_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield async_url

    cleanup_engine = create_async_engine(async_url)
    try:
        async with cleanup_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
    except Exception:
        pass
    await cleanup_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_engine(
    db_schema: str,
) -> AsyncIterator[AsyncEngine]:
    is_sqlite = "sqlite" in db_schema
    engine_kwargs = {}
    if not is_sqlite:
        engine_kwargs = {
            "pool_size": 20,
            "max_overflow": 50,
            "pool_pre_ping": True,
        }

    engine = create_async_engine(
        db_schema,
        **engine_kwargs,
    )

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    session_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    async with session_engine.begin() as connection:
        await connection.execute(text("DELETE FROM download_events"))
        await connection.execute(text("DELETE FROM outbox_events"))
        await connection.execute(text("DELETE FROM drops"))

    return async_sessionmaker(
        bind=session_engine,
        expire_on_commit=False,
    )

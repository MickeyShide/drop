import asyncio
from datetime import timedelta
from datetime import UTC
from datetime import datetime
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from drop.infrastructure.database.models import DropModel
from drop.infrastructure.repositories.drop import DropRepository
from tests.integration.factories import create_active_drop



@pytest.mark.asyncio
async def test_single_download_limit_is_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(
            session,
            max_downloads=1,
        )

        public_id = drop.public_id

    async def attempt_download() -> bool:
        async with session_factory() as session:
            repository = DropRepository(session)

            result = await repository.consume_download(
                public_id,
            )

            if result is None:
                await session.rollback()
                return False

            await session.commit()
            return True

    results = await asyncio.gather(
        *(attempt_download() for _ in range(50)),
    )

    assert sum(results) == 1

    async with session_factory() as session:
        result = await session.execute(
            select(DropModel).where(
                DropModel.public_id == public_id,
            )
        )

        persisted = result.scalar_one()

        assert persisted.download_count == 1
        assert persisted.max_downloads == 1
        assert persisted.status.value == "CONSUMED"


@pytest.mark.asyncio
async def test_multiple_download_limit_is_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(
            session,
            max_downloads=5,
        )

        public_id = drop.public_id

    async def attempt_download() -> bool:
        async with session_factory() as session:
            repository = DropRepository(session)

            result = await repository.consume_download(
                public_id,
            )

            if result is None:
                await session.rollback()
                return False

            await session.commit()
            return True

    results = await asyncio.gather(
        *(attempt_download() for _ in range(50)),
    )

    assert sum(results) == 5

    async with session_factory() as session:
        result = await session.execute(
            select(DropModel).where(
                DropModel.public_id == public_id,
            )
        )

        persisted = result.scalar_one()

        assert persisted.download_count == 5
        assert persisted.status.value == "CONSUMED"


@pytest.mark.asyncio
async def test_unlimited_drop_accepts_concurrent_downloads(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(
            session,
            max_downloads=None,
        )

        public_id = drop.public_id

    async def attempt_download() -> bool:
        async with session_factory() as session:
            repository = DropRepository(session)

            result = await repository.consume_download(
                public_id,
            )

            if result is None:
                await session.rollback()
                return False

            await session.commit()
            return True

    results = await asyncio.gather(
        *(attempt_download() for _ in range(20)),
    )

    assert sum(results) == 20


@pytest.mark.asyncio
async def test_expired_drop_cannot_be_consumed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(
            session,
            max_downloads=1,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        public_id = drop.public_id

    async with session_factory() as session:
        repository = DropRepository(session)

        result = await repository.consume_download(public_id)

        assert result is None
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.cleanup import DropCleanupService
from drop.application.services.drop import DropService
from drop.infrastructure.database.models import DropModel, DropStatus
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage
from tests.integration.factories import create_active_drop


class DummyS3Storage:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    def delete(self, storage_key: str) -> None:
        self.deleted_keys.append(storage_key)

    def create_download_url(self, storage_key: str, expires_in: int = 60) -> str:
        return f"http://localhost:9000/drop/{storage_key}?expires={expires_in}"


@pytest.mark.asyncio
async def test_cleanup_service_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(session, max_downloads=1)
        drop_id = drop.id
        storage_key = drop.storage_key

    dummy_storage = DummyS3Storage()

    async with session_factory() as session:
        repository = DropRepository(session)
        service = DropCleanupService(
            session=session,
            repository=repository,
            storage=dummy_storage,  # type: ignore[arg-type]
        )

        await service.delete_file(drop_id)

    async with session_factory() as session:
        persisted = (
            await session.execute(select(DropModel).where(DropModel.id == drop_id))
        ).scalar_one()

        assert persisted.status.value == "DELETED"
        assert persisted.deleted_at is not None
        first_deleted_at = persisted.deleted_at

    # Call delete_file a second time to verify idempotency and deleted_at preservation
    async with session_factory() as session:
        repository = DropRepository(session)
        service = DropCleanupService(
            session=session,
            repository=repository,
            storage=dummy_storage,  # type: ignore[arg-type]
        )

        await service.delete_file(drop_id)

    async with session_factory() as session:
        persisted = (
            await session.execute(select(DropModel).where(DropModel.id == drop_id))
        ).scalar_one()

        assert persisted.status.value == "DELETED"
        assert persisted.deleted_at == first_deleted_at


@pytest.mark.asyncio
async def test_consumed_drop_automatically_enqueues_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(session, max_downloads=1)
        public_id = drop.public_id
        drop_id = drop.id

    dummy_storage = DummyS3Storage()

    async with session_factory() as session:
        repository = DropRepository(session)
        service = DropService(
            session=session,
            repository=repository,
            storage=dummy_storage,  # type: ignore[arg-type]
        )

        consumed_drop = await service.consume_download(public_id)
        assert consumed_drop.status == DropStatus.CONSUMED

    with patch("drop.workers.tasks.delete_drop_file.delay") as mock_delay:
        async with session_factory() as session:
            from drop.application.services.outbox import OutboxPublisherService
            from drop.infrastructure.repositories.outbox import OutboxRepository

            publisher = OutboxPublisherService(
                session=session,
                repository=OutboxRepository(session),
            )
            count = await publisher.publish_pending_events()
            assert count == 1
            mock_delay.assert_called_once_with(str(drop_id))


@pytest.mark.asyncio
async def test_cleanup_expired_drops_finds_and_marks_expired(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    past_time = datetime.now(UTC) - timedelta(minutes=10)

    async with session_factory() as session:
        expired_drop = await create_active_drop(
            session,
            max_downloads=10,
            expires_at=past_time,
        )
        expired_id = expired_drop.id

        active_drop = await create_active_drop(
            session,
            max_downloads=10,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        active_id = active_drop.id

    dummy_storage = DummyS3Storage()

    async with session_factory() as session:
        repository = DropRepository(session)
        service = DropCleanupService(
            session=session,
            repository=repository,
            storage=dummy_storage,  # type: ignore[arg-type]
        )

        expired_ids = await service.cleanup_expired_drops()

        assert expired_id in expired_ids
        assert active_id not in expired_ids

    async with session_factory() as session:
        persisted_expired = (
            await session.execute(select(DropModel).where(DropModel.id == expired_id))
        ).scalar_one()
        assert persisted_expired.status.value == "EXPIRED"

        persisted_active = (
            await session.execute(select(DropModel).where(DropModel.id == active_id))
        ).scalar_one()
        assert persisted_active.status.value == "ACTIVE"

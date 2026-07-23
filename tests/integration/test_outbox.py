from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.drop import DropService
from drop.application.services.outbox import OutboxPublisherService
from drop.infrastructure.database.models import (
    DropStatus,
    OutboxEventModel,
    OutboxStatus,
)
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.repositories.outbox import OutboxRepository
from tests.integration.factories import create_active_drop
from tests.integration.test_cleanup import DummyS3Storage


@pytest.mark.asyncio
async def test_consumed_drop_writes_outbox_event_in_same_transaction(
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

    # Verify that OutboxEventModel was created in the database
    async with session_factory() as session:
        events = (
            await session.execute(
                select(OutboxEventModel).where(
                    OutboxEventModel.event_type == "DROP_CLEANUP_REQUIRED"
                )
            )
        ).scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.status == OutboxStatus.PENDING
        assert event.payload == {"drop_id": str(drop_id)}
        assert event.processed_at is None


@pytest.mark.asyncio
async def test_outbox_publisher_dispatches_task_and_marks_processed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(session, max_downloads=1)
        public_id = drop.public_id
        drop_id = drop.id

        repository = DropRepository(session)
        service = DropService(
            session=session,
            repository=repository,
            storage=DummyS3Storage(),  # type: ignore[arg-type]
        )
        await service.consume_download(public_id)

    # Now process pending outbox events
    with patch("drop.workers.tasks.delete_drop_file.delay") as mock_delay:
        async with session_factory() as session:
            outbox_repo = OutboxRepository(session)
            publisher_service = OutboxPublisherService(
                session=session,
                repository=outbox_repo,
            )

            processed_count = await publisher_service.publish_pending_events()
            assert processed_count == 1
            mock_delay.assert_called_once_with(str(drop_id))

    # Verify status changed to PROCESSED
    async with session_factory() as session:
        events = (
            await session.execute(select(OutboxEventModel))
        ).scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.status == OutboxStatus.PROCESSED
        assert event.processed_at is not None

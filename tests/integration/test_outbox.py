from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.drop import DropService
from drop.application.services.outbox import OutboxPublisherService
from drop.infrastructure.database.models import OutboxEventModel, OutboxStatus
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.repositories.outbox import OutboxRepository
from tests.integration.factories import create_active_drop
from tests.integration.test_cleanup import DummyS3Storage


@pytest.mark.asyncio
async def test_consumed_drop_writes_outbox_event_in_same_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop, access_token = await create_active_drop(session, max_downloads=1)
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

        body, filename, size, ctype = await service.get_download_stream(
            public_id=public_id,
            access_token=access_token,
            session_id="session1",
        )
        assert filename == "test.txt"
        await service.complete_download_grant(public_id, "session1")

    # Verify that OutboxEventModel was created in the database
    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_type == "DROP_CLEANUP_REQUIRED"
                    )
                )
            )
            .scalars()
            .all()
        )

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
        drop, access_token = await create_active_drop(session, max_downloads=1)
        public_id = drop.public_id
        drop_id = drop.id

        repository = DropRepository(session)
        service = DropService(
            session=session,
            repository=repository,
            storage=DummyS3Storage(),  # type: ignore[arg-type]
        )
        await service.get_download_stream(public_id, access_token, "session1")
        await service.complete_download_grant(public_id, "session1")

        event_id = (await session.execute(select(OutboxEventModel.id))).scalar_one()

    # Now process pending outbox events
    with patch("drop.workers.tasks.delete_drop_file.apply_async") as mock_apply_async:
        async with session_factory() as session:
            outbox_repo = OutboxRepository(session)
            publisher_service = OutboxPublisherService(
                session=session,
                repository=outbox_repo,
            )

            processed_count = await publisher_service.publish_pending_events()
            assert processed_count == 1
            mock_apply_async.assert_called_once_with(
                args=[str(drop_id)],
                task_id=str(event_id),
            )

    # Verify status changed to PROCESSED
    async with session_factory() as session:
        events = (await session.execute(select(OutboxEventModel))).scalars().all()

        assert len(events) == 1
        event = events[0]
        assert event.status == OutboxStatus.PROCESSED
        assert event.processed_at is not None


@pytest.mark.asyncio
async def test_outbox_reclaims_stale_processing_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        event = OutboxEventModel(
            event_type="DROP_CLEANUP_REQUIRED",
            payload={"drop_id": "00000000-0000-0000-0000-000000000001"},
            status=OutboxStatus.PROCESSING,
            attempts=1,
            locked_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    with patch("drop.workers.tasks.delete_drop_file.apply_async") as mock_apply_async:
        async with session_factory() as session:
            publisher = OutboxPublisherService(
                session=session,
                repository=OutboxRepository(session),
            )
            assert await publisher.publish_pending_events() == 1
            mock_apply_async.assert_called_once()

    async with session_factory() as session:
        persisted_event = await session.get(OutboxEventModel, event_id)
        assert persisted_event is not None
        assert persisted_event.status == OutboxStatus.PROCESSED
        assert persisted_event.attempts == 2


@pytest.mark.asyncio
async def test_outbox_marks_terminal_publish_failure_as_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        event = OutboxEventModel(
            event_type="UNKNOWN_EVENT",
            payload={},
            status=OutboxStatus.PENDING,
            attempts=OutboxRepository.MAX_ATTEMPTS - 1,
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    async with session_factory() as session:
        publisher = OutboxPublisherService(
            session=session,
            repository=OutboxRepository(session),
        )
        assert await publisher.publish_pending_events() == 0

    async with session_factory() as session:
        persisted_event = await session.get(OutboxEventModel, event_id)
        assert persisted_event is not None
        assert persisted_event.status == OutboxStatus.FAILED
        assert persisted_event.attempts == OutboxRepository.MAX_ATTEMPTS
        assert persisted_event.last_error is not None

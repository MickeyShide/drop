from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.infrastructure.database.models import DropModel, DropStatus
from drop.workers.tasks import (
    _cleanup_expired_drops,
    _delete_drop_file,
    _publish_outbox_events,
)
from tests.integration.factories import create_active_drop


@pytest.mark.asyncio
async def test_delete_drop_file_task_execution_and_idempotency(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(session, max_downloads=1)
        drop.status = DropStatus.CONSUMED
        await session.commit()
        drop_id = drop.id

    with patch("drop.application.services.cleanup.S3Storage") as mock_s3_cls, \
         patch("drop.workers.tasks.SessionFactory", session_factory):
        mock_storage = mock_s3_cls.return_value
        mock_storage.delete = AsyncMock()

        # Initial execution
        await _delete_drop_file(drop_id)

        async with session_factory() as session:
            persisted = await session.get(DropModel, drop_id)
            assert persisted is not None
            assert persisted.status == DropStatus.DELETED
            assert persisted.deleted_at is not None
            initial_deleted_at = persisted.deleted_at

        # Second execution (idempotency check: deleted_at must NOT change)
        await _delete_drop_file(drop_id)

        async with session_factory() as session:
            persisted = await session.get(DropModel, drop_id)
            assert persisted is not None
            assert persisted.status == DropStatus.DELETED
            assert persisted.deleted_at == initial_deleted_at


@pytest.mark.asyncio
async def test_cleanup_expired_drops_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        expired_drop = DropModel(
            public_id="expired-task-test",
            original_filename="expired.txt",
            storage_key="drops/expired/source",
            content_type="text/plain",
            size_bytes=100,
            status=DropStatus.ACTIVE,
            max_downloads=5,
            download_count=0,
            expires_at=now - timedelta(minutes=10),
            created_at=now - timedelta(minutes=20),
        )
        session.add(expired_drop)
        await session.commit()
        drop_id = expired_drop.id

    with patch("drop.workers.tasks.SessionFactory", session_factory):
        count = await _cleanup_expired_drops()
        assert count >= 1

    async with session_factory() as session:
        persisted = await session.get(DropModel, drop_id)
        assert persisted is not None
        assert persisted.status == DropStatus.EXPIRED


@pytest.mark.asyncio
async def test_publish_outbox_events_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with patch("drop.workers.tasks.delete_drop_file.delay") as mock_delay, \
         patch("drop.workers.tasks.SessionFactory", session_factory):
        mock_delay.return_value = None
        processed = await _publish_outbox_events()
        assert isinstance(processed, int)

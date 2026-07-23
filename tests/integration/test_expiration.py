from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.cleanup import DropCleanupService
from drop.application.services.drop import DropService
from drop.domain.exceptions import DropExpiredError
from drop.infrastructure.database.models import (
    DropModel,
    DropStatus,
    OutboxEventModel,
    OutboxStatus,
)
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage


@pytest.mark.asyncio
async def test_drop_service_rejects_expired_drop_immediately(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        expired_drop = DropModel(
            public_id="expired-api-test",
            original_filename="expired.txt",
            storage_key="drops/expired/source",
            content_type="text/plain",
            size_bytes=100,
            status=DropStatus.ACTIVE,
            max_downloads=5,
            download_count=0,
            expires_at=now - timedelta(seconds=1),
            created_at=now - timedelta(minutes=10),
        )
        session.add(expired_drop)
        await session.commit()

    async with session_factory() as session:
        service = DropService(
            session=session,
            repository=DropRepository(session),
            storage=MagicMock(spec=S3Storage),
        )

        with pytest.raises(DropExpiredError):
            await service.consume_download("expired-api-test")


@pytest.mark.asyncio
async def test_cleanup_expired_drops_creates_outbox_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        expired_drop = DropModel(
            public_id="expired-outbox-test",
            original_filename="expired.txt",
            storage_key="drops/expired/source",
            content_type="text/plain",
            size_bytes=100,
            status=DropStatus.ACTIVE,
            max_downloads=5,
            download_count=0,
            expires_at=now - timedelta(minutes=5),
            created_at=now - timedelta(minutes=15),
        )
        session.add(expired_drop)
        await session.commit()
        drop_id = expired_drop.id

    async with session_factory() as session:
        service = DropCleanupService(
            session=session,
            repository=DropRepository(session),
            storage=MagicMock(),
        )

        expired_ids = await service.cleanup_expired_drops()
        assert drop_id in expired_ids

    async with session_factory() as session:
        persisted = await session.get(DropModel, drop_id)
        assert persisted is not None
        assert persisted.status == DropStatus.EXPIRED

        result = await session.execute(
            select(OutboxEventModel).where(
                OutboxEventModel.event_type == "DROP_CLEANUP_REQUIRED",
                OutboxEventModel.status == OutboxStatus.PENDING,
            )
        )
        outbox_events = result.scalars().all()
        matching = [e for e in outbox_events if e.payload.get("drop_id") == str(drop_id)]
        assert len(matching) == 1

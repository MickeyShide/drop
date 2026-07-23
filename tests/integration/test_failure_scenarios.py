import io
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.cleanup import DropCleanupService
from drop.application.services.drop import DropService
from drop.infrastructure.database.models import DropModel, DropStatus
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage
from tests.integration.factories import create_active_drop


@pytest.mark.asyncio
async def test_s3_upload_failure_marks_drop_failed_and_cleans_partial_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    mock_storage = MagicMock(spec=S3Storage)
    mock_storage.upload.side_effect = Exception("S3 bucket connection timeout")

    async with session_factory() as session:
        service = DropService(
            session=session,
            repository=DropRepository(session),
            storage=mock_storage,
        )

        fake_file = UploadFile(
            filename="test_fail.txt",
            file=io.BytesIO(b"sample file content for upload failure test"),
            headers={"content-type": "text/plain"},
        )

        with pytest.raises(Exception, match="S3 bucket connection timeout"):
            await service.create(
                file=fake_file,
                expires_in_seconds=3600,
                max_downloads=5,
            )

    mock_storage.delete.assert_called_once()


@pytest.mark.asyncio
async def test_s3_delete_error_during_cleanup_raises_exception_for_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        drop = await create_active_drop(session, max_downloads=1)
        drop.status = DropStatus.CONSUMED
        await session.commit()
        drop_id = drop.id

    mock_storage = MagicMock(spec=S3Storage)
    mock_storage.delete.side_effect = Exception("S3 Service Unavailable")

    async with session_factory() as session:
        service = DropCleanupService(
            session=session,
            repository=DropRepository(session),
            storage=mock_storage,
        )

        with pytest.raises(Exception, match="S3 Service Unavailable"):
            await service.delete_file(drop_id)

    async with session_factory() as session:
        persisted = await session.get(DropModel, drop_id)
        assert persisted is not None
        assert persisted.status != DropStatus.DELETED
        assert persisted.deleted_at is None

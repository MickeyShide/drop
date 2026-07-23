import io
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from drop.application.services.drop import DropService
from drop.config import get_settings
from drop.domain.exceptions import FileTooLargeError
from drop.domain.sanitization import sanitize_content_type, sanitize_filename
from drop.infrastructure.database.models import DropModel, DropStatus
from drop.infrastructure.repositories.drop import DropRepository
from tests.integration.test_cleanup import DummyS3Storage


def test_filename_sanitization() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32.dll") == "system32.dll"
    assert sanitize_filename("\x00test\x1f.txt") == "test.txt"
    assert sanitize_filename("") == "file"
    assert sanitize_filename(None) == "file"
    assert sanitize_filename("   ") == "file"


def test_content_type_sanitization() -> None:
    assert sanitize_content_type("  text/html  ") == "text/html"
    assert sanitize_content_type("") == "application/octet-stream"
    assert sanitize_content_type(None) == "application/octet-stream"
    assert sanitize_content_type("invalid") == "application/octet-stream"


@pytest.mark.asyncio
async def test_upload_exceeding_max_size_raises_file_too_large(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = get_settings()

    # Create a 2 MB file when limit is set to 1 MB
    large_data = b"x" * (2 * 1024 * 1024)
    file_obj = UploadFile(filename="large.txt", file=io.BytesIO(large_data))

    dummy_storage = DummyS3Storage()

    with patch.object(settings, "max_upload_size_bytes", 1 * 1024 * 1024):
        async with session_factory() as session:
            service = DropService(
                session=session,
                repository=DropRepository(session),
                storage=dummy_storage,  # type: ignore[arg-type]
            )

            with pytest.raises(FileTooLargeError):
                await service.create(
                    file=file_obj,
                    expires_in_seconds=3600,
                    max_downloads=1,
                )

    # Verify no drop was created in the database
    async with session_factory() as session:
        drops = (await session.execute(select(DropModel))).scalars().all()
        assert len(drops) == 0


@pytest.mark.asyncio
async def test_s3_upload_failure_triggers_cleanup_and_failed_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    file_obj = UploadFile(filename="../../secret.txt", file=io.BytesIO(b"test content"))

    class FailingStorage(DummyS3Storage):
        def upload(self, file, storage_key, content_type) -> None:
            raise RuntimeError("S3 connection lost")

    failing_storage = FailingStorage()

    async with session_factory() as session:
        service = DropService(
            session=session,
            repository=DropRepository(session),
            storage=failing_storage,  # type: ignore[arg-type]
        )

        with pytest.raises(RuntimeError, match="S3 connection lost"):
            await service.create(
                file=file_obj,
                expires_in_seconds=3600,
                max_downloads=1,
            )

    # Verify that partial object cleanup was attempted
    assert len(failing_storage.deleted_keys) == 1

    # Verify that drop status in DB is FAILED
    async with session_factory() as session:
        drops = (await session.execute(select(DropModel))).scalars().all()
        assert len(drops) == 1
        failed_drop = drops[0]
        assert failed_drop.status == DropStatus.FAILED
        assert failed_drop.original_filename == "secret.txt"

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from drop.config import get_settings
from drop.domain.exceptions import (
    DropConsumedError,
    DropExpiredError,
    DropNotFoundError,
    DropNotReadyError,
    FileTooLargeError,
)
from drop.domain.public_id import generate_public_id
from drop.domain.sanitization import sanitize_content_type, sanitize_filename
from drop.infrastructure.database.models import (
    DropModel,
    DropStatus,
    OutboxEventModel,
    OutboxStatus,
)
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage
from drop.logging import drop_id_var

logger = logging.getLogger("drop.service")


class DropService:
    def __init__(
        self, session: AsyncSession, repository: DropRepository, storage: S3Storage
    ) -> None:
        self._session = session
        self._repository = repository
        self._storage = storage

    async def consume_download(
        self,
        public_id: str,
    ) -> DropModel:
        drop = await self._repository.consume_download(public_id)

        if drop is not None:
            if drop.status == DropStatus.CONSUMED:
                outbox_event = OutboxEventModel(
                    event_type="DROP_CLEANUP_REQUIRED",
                    payload={"drop_id": str(drop.id)},
                    status=OutboxStatus.PENDING,
                )
                self._session.add(outbox_event)

            await self._session.commit()
            return drop

        existing = await self._repository.get_by_public_id(public_id)

        if existing is None:
            raise DropNotFoundError

        now = datetime.now(UTC)

        if existing.expires_at <= now:
            raise DropExpiredError

        if existing.status == DropStatus.CONSUMED:
            raise DropConsumedError

        raise DropNotReadyError

    async def create(
        self,
        file: UploadFile,
        expires_in_seconds: int,
        max_downloads: int | None,
    ) -> DropModel:
        settings = get_settings()
        now = datetime.now(UTC)

        drop_id = uuid.uuid4()
        token = drop_id_var.set(str(drop_id))
        public_id = generate_public_id()
        storage_key = f"drops/{drop_id}/source"

        clean_filename = sanitize_filename(file.filename)
        clean_content_type = sanitize_content_type(file.content_type)

        await file.seek(0)

        size_bytes = 0

        while chunk := await file.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > settings.max_upload_size_bytes:
                logger.warning(
                    "Upload rejected: file size exceeds limit",
                    extra={"size_bytes": size_bytes, "max_size": settings.max_upload_size_bytes},
                )
                drop_id_var.reset(token)
                raise FileTooLargeError

        await file.seek(0)

        drop = DropModel(
            id=drop_id,
            public_id=public_id,
            original_filename=clean_filename,
            storage_key=storage_key,
            content_type=clean_content_type,
            size_bytes=size_bytes,
            status=DropStatus.UPLOADING,
            max_downloads=max_downloads,
            download_count=0,
            expires_at=now + timedelta(seconds=expires_in_seconds),
            created_at=now,
        )

        await self._repository.add(drop)
        await self._session.commit()

        try:
            await run_in_threadpool(
                self._storage.upload,
                file.file,
                storage_key,
                clean_content_type,
            )
        except Exception as e:
            logger.error("S3 upload failed, marking drop as FAILED", exc_info=e)
            try:
                await run_in_threadpool(
                    self._storage.delete,
                    storage_key,
                )
            except Exception:
                pass

            drop.status = DropStatus.FAILED
            await self._session.commit()
            drop_id_var.reset(token)
            raise

        drop.status = DropStatus.ACTIVE

        await self._session.commit()
        await self._session.refresh(drop)

        logger.info(
            "Drop created successfully",
            extra={"size_bytes": size_bytes, "public_id": public_id},
        )
        drop_id_var.reset(token)

        return drop

    async def get_by_public_id(self, public_id: str) -> DropModel:
        drop = await self._repository.get_by_public_id(public_id)
        if drop is None:
            raise DropNotFoundError
        return drop

    async def get_download_url(
        self,
        public_id: str,
    ) -> str:
        drop = await self.consume_download(public_id)

        return await run_in_threadpool(
            self._storage.create_download_url,
            drop.storage_key,
            60,
        )

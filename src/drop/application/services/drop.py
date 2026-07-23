from drop.infrastructure.storage.s3 import S3Storage
from fastapi import UploadFile
import uuid
from fastapi.concurrency import run_in_threadpool
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from drop.domain.exceptions import DropNotFoundError

from drop.domain.public_id import generate_public_id
from drop.infrastructure.database.models import (
    DropModel,
    DropStatus,
)
from drop.infrastructure.repositories.drop import DropRepository


class DropService:
    def __init__(self, session: AsyncSession, repository: DropRepository, storage: S3Storage) -> None:
        self._session = session
        self._repository = repository
        self._storage = storage

    async def create(
        self,
        file: UploadFile,
        expires_in_seconds: int,
        max_downloads: int | None,
    ) -> DropModel:
        now = datetime.now(UTC)

        drop_id = uuid.uuid4()
        public_id = generate_public_id()
        storage_key = f"drops/{drop_id}/source"

        await file.seek(0)

        size_bytes = 0

        while chunk := await file.read(1024 * 1024):
            size_bytes += len(chunk)

        await file.seek(0)

        drop = DropModel(
            id=drop_id,
            public_id=public_id,
            original_filename=file.filename or "file",
            storage_key=storage_key,
            content_type=file.content_type,
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
                file.content_type,
            )
        except Exception:
            drop.status = DropStatus.FAILED
            await self._session.commit()
            raise

        drop.status = DropStatus.ACTIVE

        await self._session.commit()
        await self._session.refresh(drop)

        return drop

    async def get_by_public_id(self, public_id: str) -> DropModel:
        drop = await self._repository.get_by_public_id(public_id)
        if drop is None:
            raise DropNotFoundError
        return drop

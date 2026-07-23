from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from drop.infrastructure.database.models import DropStatus
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage


class DropCleanupService:
    def __init__(
        self,
        session: AsyncSession,
        repository: DropRepository,
        storage: S3Storage,
    ) -> None:
        self._session = session
        self._repository = repository
        self._storage = storage

    async def delete_file(self, drop_id: UUID) -> None:
        drop = await self._repository.get_by_id(drop_id)

        if drop is None:
            return

        if drop.status == DropStatus.DELETED:
            return

        await run_in_threadpool(
            self._storage.delete,
            drop.storage_key,
        )

        drop.status = DropStatus.DELETED
        drop.deleted_at = datetime.now(UTC)

        await self._session.commit()
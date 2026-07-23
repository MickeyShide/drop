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
        drop.deleted_at = drop.deleted_at or datetime.now(UTC)

        await self._session.commit()

    async def cleanup_expired_drops(
        self,
        now: datetime | None = None,
    ) -> list[UUID]:
        expired_drops = await self._repository.get_expired_drops(now)

        if not expired_drops:
            return []

        expired_ids: list[UUID] = []

        for drop in expired_drops:
            drop.status = DropStatus.EXPIRED
            expired_ids.append(drop.id)

        await self._session.commit()

        return expired_ids
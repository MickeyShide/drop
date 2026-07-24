from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from drop.infrastructure.database.models import (
    DropStatus,
    OutboxEventModel,
    OutboxStatus,
)
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

        if await self._repository.count_active_grants(drop_id) > 0:
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
        cutoff = now or datetime.now(UTC)
        expired_drops = await self._repository.get_expired_drops(cutoff)
        stale_grant_drop_ids = await self._repository.expire_stale_grants(cutoff)

        expired_ids: list[UUID] = []

        for drop in expired_drops:
            drop.status = DropStatus.EXPIRED
            expired_ids.append(drop.id)

        candidate_ids = {drop.id for drop in expired_drops}
        candidate_ids.update(stale_grant_drop_ids)
        for drop_id in candidate_ids:
            candidate_drop = await self._repository.get_by_id(drop_id)
            if candidate_drop is None or candidate_drop.status not in (
                DropStatus.EXPIRED,
                DropStatus.CONSUMED,
            ):
                continue
            if await self._repository.count_active_grants(drop_id, cutoff) > 0:
                continue
            existing_event = await self._session.execute(
                select(OutboxEventModel).where(
                    OutboxEventModel.event_type == "DROP_CLEANUP_REQUIRED",
                    OutboxEventModel.payload["drop_id"].as_string() == str(drop_id),
                )
            )
            if existing_event.scalar_one_or_none() is None:
                self._session.add(
                    OutboxEventModel(
                        event_type="DROP_CLEANUP_REQUIRED",
                        payload={"drop_id": str(drop_id)},
                        status=OutboxStatus.PENDING,
                    )
                )

        if expired_drops or stale_grant_drop_ids:
            await self._session.commit()

        return expired_ids

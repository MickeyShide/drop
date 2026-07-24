from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from drop.infrastructure.database.models import (
    DropStatus,
    OutboxEventModel,
    OutboxStatus,
)
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.repositories.outbox import OutboxRepository
from drop.infrastructure.storage.s3 import S3Storage


class DropCleanupService:
    # A successful 100 MiB upload can take time on a slow link. Recovery only
    # touches rows that stayed UPLOADING for an hour, avoiding a new public env
    # knob while still repairing crashes between PostgreSQL and MinIO.
    UPLOAD_RECOVERY_GRACE = timedelta(hours=1)

    def __init__(
        self,
        session: AsyncSession,
        repository: DropRepository,
        storage: S3Storage,
    ) -> None:
        self._session = session
        self._repository = repository
        self._outbox_repository = OutboxRepository(session)
        self._storage = storage

    async def delete_file(self, drop_id: UUID) -> None:
        drop = await self._repository.get_by_id_for_update(drop_id)

        if drop is None:
            return

        if drop.status == DropStatus.DELETED:
            return

        if await self._repository.count_active_grants(drop_id) > 0:
            return

        # Make the external side effect resumable. If the worker dies after
        # this commit, the periodic sweep will enqueue DELETING again.
        drop.status = DropStatus.DELETING
        await self._session.commit()

        await run_in_threadpool(
            self._storage.delete,
            drop.storage_key,
        )

        drop.status = DropStatus.DELETED
        drop.deleted_at = drop.deleted_at or datetime.now(UTC)

        await self._session.commit()

    async def recover_stale_uploads(self, now: datetime) -> int:
        stale_uploads = await self._repository.get_stale_uploads(
            now - self.UPLOAD_RECOVERY_GRACE
        )
        recovered = 0

        for drop in stale_uploads:
            metadata = await run_in_threadpool(
                self._storage.get_object_metadata,
                drop.storage_key,
            )
            if metadata is not None and metadata[0] == drop.size_bytes:
                drop.status = (
                    DropStatus.EXPIRED if drop.expires_at <= now else DropStatus.ACTIVE
                )
            else:
                if metadata is not None:
                    await run_in_threadpool(self._storage.delete, drop.storage_key)
                drop.status = DropStatus.FAILED
            recovered += 1

        return recovered

    async def _enqueue_cleanup_if_needed(self, drop_id: UUID) -> bool:
        if await self._repository.count_active_grants(drop_id) > 0:
            return False
        if await self._outbox_repository.has_open_cleanup_event(drop_id):
            return False

        self._session.add(
            OutboxEventModel(
                event_type="DROP_CLEANUP_REQUIRED",
                payload={"drop_id": str(drop_id)},
                status=OutboxStatus.PENDING,
            )
        )
        return True

    async def cleanup_expired_drops(
        self,
        now: datetime | None = None,
    ) -> list[UUID]:
        cutoff = now or datetime.now(UTC)
        expired_drops = await self._repository.get_expired_drops(cutoff)
        stale_grant_drop_ids = await self._repository.expire_stale_grants(cutoff)
        recovered_uploads = await self.recover_stale_uploads(cutoff)

        expired_ids: list[UUID] = []

        for drop in expired_drops:
            drop.status = DropStatus.EXPIRED
            expired_ids.append(drop.id)

        cleanup_candidates = await self._repository.get_cleanup_candidates()
        queued_count = 0
        for candidate in cleanup_candidates:
            if await self._enqueue_cleanup_if_needed(candidate.id):
                queued_count += 1

        if expired_drops or stale_grant_drop_ids or recovered_uploads or queued_count:
            await self._session.commit()

        return expired_ids

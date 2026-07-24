from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.database.models import OutboxEventModel, OutboxStatus


class OutboxRepository:
    PROCESSING_LEASE = timedelta(minutes=1)
    MAX_ATTEMPTS = 10

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEventModel) -> OutboxEventModel:
        self._session.add(event)
        await self._session.flush()
        return event

    async def claim_pending_events(
        self,
        batch_size: int = 100,
        now: datetime | None = None,
    ) -> list[OutboxEventModel]:
        claimed_at = now or datetime.now(UTC)
        stale_before = claimed_at - self.PROCESSING_LEASE
        stmt = (
            select(OutboxEventModel)
            .where(
                or_(
                    OutboxEventModel.status == OutboxStatus.PENDING,
                    and_(
                        OutboxEventModel.status == OutboxStatus.PROCESSING,
                        or_(
                            OutboxEventModel.locked_at.is_(None),
                            OutboxEventModel.locked_at <= stale_before,
                        ),
                    ),
                )
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        result = await self._session.execute(stmt)
        events = list(result.scalars().all())
        for event in events:
            event.status = OutboxStatus.PROCESSING
            event.attempts += 1
            event.locked_at = claimed_at
            event.last_error = None
        await self._session.flush()
        return events

    async def mark_processed(
        self,
        event_ids: list[UUID],
        now: datetime | None = None,
    ) -> None:
        if not event_ids:
            return

        cutoff = now or datetime.now(UTC)

        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id.in_(event_ids))
            .values(
                status=OutboxStatus.PROCESSED,
                processed_at=cutoff,
                locked_at=None,
                last_error=None,
            )
        )

        await self._session.execute(stmt)

    async def mark_delivery_failure(
        self, event: OutboxEventModel, error: Exception
    ) -> None:
        event.status = (
            OutboxStatus.FAILED
            if event.attempts >= self.MAX_ATTEMPTS
            else OutboxStatus.PENDING
        )
        event.locked_at = None
        event.last_error = str(error)[:512]
        await self._session.flush()

    async def has_open_cleanup_event(self, drop_id: UUID) -> bool:
        result = await self._session.execute(
            select(OutboxEventModel.id)
            .where(
                OutboxEventModel.event_type == "DROP_CLEANUP_REQUIRED",
                OutboxEventModel.payload["drop_id"].as_string() == str(drop_id),
                OutboxEventModel.status.in_(
                    (OutboxStatus.PENDING, OutboxStatus.PROCESSING)
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_all_events(self, limit: int = 50) -> list[OutboxEventModel]:
        stmt = (
            select(OutboxEventModel)
            .order_by(OutboxEventModel.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

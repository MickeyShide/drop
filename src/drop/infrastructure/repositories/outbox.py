from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.database.models import OutboxEventModel, OutboxStatus


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: OutboxEventModel) -> OutboxEventModel:
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_pending_events(
        self,
        batch_size: int = 100,
    ) -> list[OutboxEventModel]:
        stmt = (
            select(OutboxEventModel)
            .where(OutboxEventModel.status == OutboxStatus.PENDING)
            .order_by(OutboxEventModel.created_at.asc())
            .limit(batch_size)
        )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

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
            )
        )

        await self._session.execute(stmt)

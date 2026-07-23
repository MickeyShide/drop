from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.repositories.outbox import OutboxRepository


class OutboxPublisherService:
    def __init__(
        self,
        session: AsyncSession,
        repository: OutboxRepository,
    ) -> None:
        self._session = session
        self._repository = repository

    async def publish_pending_events(self, batch_size: int = 100) -> int:
        events = await self._repository.get_pending_events(batch_size=batch_size)

        if not events:
            return 0

        from drop.workers.tasks import delete_drop_file

        processed_ids = []

        for event in events:
            if event.event_type == "DROP_CLEANUP_REQUIRED":
                drop_id = event.payload.get("drop_id")
                if drop_id:
                    delete_drop_file.delay(str(drop_id))

            processed_ids.append(event.id)

        await self._repository.mark_processed(processed_ids)
        await self._session.commit()

        return len(processed_ids)

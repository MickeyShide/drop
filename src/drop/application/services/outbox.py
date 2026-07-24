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
        events = await self._repository.claim_pending_events(batch_size=batch_size)

        if not events:
            return 0

        # Persist the claim before broker I/O. A crashed publisher leaves a
        # recoverable PROCESSING event which can be reclaimed after its lease.
        await self._session.commit()

        from drop.workers.tasks import delete_drop_file

        published_count = 0

        for event in events:
            try:
                if event.event_type != "DROP_CLEANUP_REQUIRED":
                    raise ValueError(
                        f"Unsupported outbox event type: {event.event_type}"
                    )
                drop_id = event.payload.get("drop_id")
                if not isinstance(drop_id, str) or not drop_id:
                    raise ValueError("Outbox cleanup event has no drop_id")

                # A stable task ID makes duplicate publication traceable. It
                # does not claim exactly-once broker delivery; the delete task
                # remains deliberately idempotent.
                delete_drop_file.apply_async(
                    args=[drop_id],
                    task_id=str(event.id),
                )
                await self._repository.mark_processed([event.id])
                await self._session.commit()
                published_count += 1
            except Exception as exc:
                await self._repository.mark_delivery_failure(event, exc)
                await self._session.commit()

        return published_count

import asyncio
from uuid import UUID

from drop.infrastructure.database.engine import SessionFactory
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage
from drop.application.services.cleanup import DropCleanupService
from drop.workers.celery_app import celery_app


@celery_app.task(name="drop.ping")
def ping() -> str:
    return "pong"


@celery_app.task(
    bind=True,
    name="drop.delete_file",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
)
def delete_drop_file(self, drop_id: str) -> None:
    asyncio.run(_delete_drop_file(UUID(drop_id)))


async def _delete_drop_file(drop_id: UUID) -> None:
    async with SessionFactory() as session:
        service = DropCleanupService(
            session=session,
            repository=DropRepository(session),
            storage=S3Storage(),
        )

        await service.delete_file(drop_id)


@celery_app.task(
    name="drop.cleanup_expired",
    acks_late=True,
)
def cleanup_expired_drops() -> int:
    return asyncio.run(_cleanup_expired_drops())


async def _cleanup_expired_drops() -> int:
    async with SessionFactory() as session:
        service = DropCleanupService(
            session=session,
            repository=DropRepository(session),
            storage=S3Storage(),
        )

        expired_ids = await service.cleanup_expired_drops()
        return len(expired_ids)


@celery_app.task(
    name="drop.publish_outbox",
    acks_late=True,
)
def publish_outbox_events() -> int:
    return asyncio.run(_publish_outbox_events())


async def _publish_outbox_events() -> int:
    async with SessionFactory() as session:
        from drop.application.services.outbox import OutboxPublisherService
        from drop.infrastructure.repositories.outbox import OutboxRepository

        service = OutboxPublisherService(
            session=session,
            repository=OutboxRepository(session),
        )

        return await service.publish_pending_events()

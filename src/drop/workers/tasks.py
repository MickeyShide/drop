import asyncio
import logging
from uuid import UUID

from drop.application.services.cleanup import DropCleanupService
from drop.infrastructure.database.engine import SessionFactory
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage
from drop.logging import drop_id_var, task_id_var
from drop.workers.celery_app import celery_app

logger = logging.getLogger("drop.workers")


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
    token = task_id_var.set(str(self.request.id))
    try:
        logger.info("Executing delete_drop_file task", extra={"drop_id": drop_id})
        asyncio.run(_delete_drop_file(UUID(drop_id)))
    finally:
        task_id_var.reset(token)


async def _delete_drop_file(drop_id: UUID) -> None:
    d_token = drop_id_var.set(str(drop_id))
    try:
        async with SessionFactory() as session:
            service = DropCleanupService(
                session=session,
                repository=DropRepository(session),
                storage=S3Storage(),
            )

            await service.delete_file(drop_id)
    finally:
        drop_id_var.reset(d_token)


@celery_app.task(
    bind=True,
    name="drop.cleanup_expired",
    acks_late=True,
)
def cleanup_expired_drops(self) -> int:
    token = task_id_var.set(str(self.request.id))
    try:
        logger.info("Executing cleanup_expired_drops task")
        return asyncio.run(_cleanup_expired_drops())
    finally:
        task_id_var.reset(token)


async def _cleanup_expired_drops() -> int:
    async with SessionFactory() as session:
        service = DropCleanupService(
            session=session,
            repository=DropRepository(session),
            storage=S3Storage(),
        )

        expired_ids = await service.cleanup_expired_drops()
        if expired_ids:
            logger.info("Expired drops cleanup processed", extra={"count": len(expired_ids)})
        return len(expired_ids)


@celery_app.task(
    bind=True,
    name="drop.publish_outbox",
    acks_late=True,
)
def publish_outbox_events(self) -> int:
    token = task_id_var.set(str(self.request.id))
    try:
        return asyncio.run(_publish_outbox_events())
    finally:
        task_id_var.reset(token)


async def _publish_outbox_events() -> int:
    async with SessionFactory() as session:
        from drop.application.services.outbox import OutboxPublisherService
        from drop.infrastructure.repositories.outbox import OutboxRepository

        service = OutboxPublisherService(
            session=session,
            repository=OutboxRepository(session),
        )

        processed = await service.publish_pending_events()
        if processed > 0:
            logger.info("Outbox publisher processed pending events", extra={"processed_count": processed})
        return processed
import logging
from typing import Any
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from drop.config import get_settings
from drop.domain.exceptions import (
    DropConsumedError,
    DropExpiredError,
    DropNotFoundError,
    DropNotReadyError,
    FileTooLargeError,
)
from drop.domain.public_id import generate_public_id
from drop.domain.sanitization import sanitize_content_type, sanitize_filename
from drop.infrastructure.database.models import (
    DownloadEventModel,
    DropModel,
    DropStatus,
    OutboxEventModel,
    OutboxStatus,
)
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.repositories.outbox import OutboxRepository
from drop.infrastructure.storage.s3 import S3Storage
from drop.logging import drop_id_var
from drop.metrics import (
    DROP_DOWNLOADS_REJECTED_TOTAL,
    DROP_DOWNLOADS_TOTAL,
    DROP_UPLOADS_TOTAL,
)

logger = logging.getLogger("drop.service")


class DropService:
    def __init__(
        self,
        session: AsyncSession,
        repository: DropRepository,
        storage: S3Storage,
        outbox_repo: OutboxRepository | None = None,
    ) -> None:
        self._session = session
        self._repository = repository
        self._storage = storage
        self._outbox_repo = outbox_repo or OutboxRepository(session)

    async def consume_download(
        self,
        public_id: str,
    ) -> DropModel:
        drop = await self._repository.consume_download(public_id)

        if drop is not None:
            DROP_DOWNLOADS_TOTAL.inc()
            if drop.status == DropStatus.CONSUMED:
                outbox_event = OutboxEventModel(
                    event_type="DROP_CLEANUP_REQUIRED",
                    payload={"drop_id": str(drop.id)},
                    status=OutboxStatus.PENDING,
                )
                self._session.add(outbox_event)

            await self._session.commit()
            return drop

        existing = await self._repository.get_by_public_id(public_id)

        if existing is None:
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_found").inc()
            raise DropNotFoundError

        now = datetime.now(UTC)

        if existing.expires_at <= now:
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="expired").inc()
            raise DropExpiredError

        if existing.status == DropStatus.CONSUMED:
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="consumed").inc()
            raise DropConsumedError

        DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_ready").inc()
        raise DropNotReadyError

    async def create(
        self,
        file: UploadFile,
        expires_in_seconds: int,
        max_downloads: int | None,
    ) -> DropModel:
        settings = get_settings()
        now = datetime.now(UTC)

        drop_id = uuid.uuid4()
        token = drop_id_var.set(str(drop_id))
        public_id = generate_public_id()
        storage_key = f"drops/{drop_id}/source"

        clean_filename = sanitize_filename(file.filename)
        clean_content_type = sanitize_content_type(file.content_type)

        await file.seek(0)

        size_bytes = 0

        while chunk := await file.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > settings.max_upload_size_bytes:
                DROP_UPLOADS_TOTAL.labels(status="rejected").inc()
                logger.warning(
                    "Upload rejected: file size exceeds limit",
                    extra={"size_bytes": size_bytes, "max_size": settings.max_upload_size_bytes},
                )
                drop_id_var.reset(token)
                raise FileTooLargeError

        await file.seek(0)

        drop = DropModel(
            id=drop_id,
            public_id=public_id,
            original_filename=clean_filename,
            storage_key=storage_key,
            content_type=clean_content_type,
            size_bytes=size_bytes,
            status=DropStatus.UPLOADING,
            max_downloads=max_downloads,
            download_count=0,
            expires_at=now + timedelta(seconds=expires_in_seconds),
            created_at=now,
        )

        await self._repository.add(drop)
        await self._session.commit()

        try:
            await run_in_threadpool(
                self._storage.upload,
                file.file,
                storage_key,
                clean_content_type,
            )
        except Exception as e:
            DROP_UPLOADS_TOTAL.labels(status="failed").inc()
            logger.error("S3 upload failed, marking drop as FAILED", exc_info=e)
            try:
                await run_in_threadpool(
                    self._storage.delete,
                    storage_key,
                )
            except Exception:
                pass

            drop.status = DropStatus.FAILED
            await self._session.commit()
            drop_id_var.reset(token)
            raise

        drop.status = DropStatus.ACTIVE

        await self._session.commit()
        await self._session.refresh(drop)

        DROP_UPLOADS_TOTAL.labels(status="success").inc()
        logger.info(
            "Drop created successfully",
            extra={"size_bytes": size_bytes, "public_id": public_id},
        )
        drop_id_var.reset(token)

        return drop

    async def get_by_public_id(self, public_id: str) -> DropModel:
        drop = await self._repository.get_by_public_id(public_id)
        if drop is None:
            raise DropNotFoundError
        return drop

    async def get_download_url(
        self,
        public_id: str,
    ) -> str:
        drop = await self.consume_download(public_id)

        return await run_in_threadpool(
            self._storage.create_download_url,
            drop.storage_key,
            60,
        )

    async def get_download_stream(
        self,
        public_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        duration_ms: float | None = None,
    ) -> tuple[Any, str, int, str | None]:
        drop = await self.consume_download(public_id)

        try:
            event = DownloadEventModel(
                drop_id=drop.id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                download_number=drop.download_count,
                duration_ms=duration_ms,
            )
            await self._repository.record_download_event(event)
            await self._session.commit()
        except Exception as err:
            logger.warning("Failed to record download event", exc_info=err)

        body, size, content_type = await run_in_threadpool(
            self._storage.get_object,
            drop.storage_key,
        )
        return body, drop.original_filename, size, content_type

    async def get_admin_logs(self) -> dict[str, Any]:
        drops = await self._repository.get_all_drops(50)
        events = await self._repository.get_all_download_events(50)
        outbox_events = await self._outbox_repo.get_all_events(50)

        drop_map = {d.id: d for d in drops}

        formatted_events = []
        for e in events:
            d = drop_map.get(e.drop_id)
            formatted_events.append({
                "id": e.id,
                "request_id": e.request_id,
                "ip_address": e.ip_address,
                "filename": d.original_filename if d else "Unknown",
                "public_id": d.public_id if d else "Unknown",
                "download_number": e.download_number,
                "max_downloads": d.max_downloads if d else None,
                "duration_ms": round(e.duration_ms, 2) if e.duration_ms is not None else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            })

        formatted_drops = [
            {
                "public_id": d.public_id,
                "original_filename": d.original_filename,
                "size_bytes": d.size_bytes,
                "download_count": d.download_count,
                "max_downloads": d.max_downloads,
                "status": d.status.value if hasattr(d.status, "value") else str(d.status),
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "expires_at": d.expires_at.isoformat() if d.expires_at else None,
            }
            for d in drops
        ]

        formatted_tasks = [
            {
                "id": str(t.id),
                "event_type": t.event_type,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "payload": t.payload,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "processed_at": t.processed_at.isoformat() if t.processed_at else None,
            }
            for t in outbox_events
        ]

        return {
            "drops": formatted_drops,
            "download_events": formatted_events,
            "tasks": formatted_tasks,
        }

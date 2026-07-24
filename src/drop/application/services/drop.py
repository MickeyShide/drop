import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drop.config import get_settings
from drop.api.rate_limit import rate_limit_upload_bytes
from drop.domain.exceptions import (
    DropConsumedError,
    DropExpiredError,
    DropNotFoundError,
    DropNotReadyError,
    FileTooLargeError,
)
from drop.domain.public_id import generate_public_id
from drop.domain.sanitization import sanitize_content_type, sanitize_filename
from drop.domain.security import (
    compute_session_hash,
    compute_token_hash,
    generate_access_token,
    pseudonymize_ip,
    verify_access_token,
)
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
    DOWNLOAD_GRANTS_CREATED_TOTAL,
    DOWNLOAD_GRANTS_REUSED_TOTAL,
    INVALID_CAPABILITY_TOTAL,
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

    async def verify_drop_access(
        self,
        public_id: str,
        access_token: str | None,
    ) -> DropModel:
        """Verify capability access token in constant time.

        Returns generic 404 DropNotFoundError on invalid token or missing drop to prevent enumeration.
        """
        if not access_token:
            INVALID_CAPABILITY_TOTAL.inc()
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_found").inc()
            raise DropNotFoundError

        drop = await self._repository.get_by_public_id(public_id)
        if drop is None:
            INVALID_CAPABILITY_TOTAL.inc()
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_found").inc()
            raise DropNotFoundError

        settings = get_settings()
        if not verify_access_token(
            access_token, drop.access_token_hash, settings.drop_token_pepper
        ):
            INVALID_CAPABILITY_TOTAL.inc()
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_found").inc()
            raise DropNotFoundError

        return drop

    async def get_metadata(
        self,
        public_id: str,
        access_token: str | None,
    ) -> DropModel:
        """Get drop metadata without consuming any download slots or grants."""
        drop = await self.verify_drop_access(public_id, access_token)
        now = datetime.now(UTC)

        if drop.expires_at <= now:
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="expired").inc()
            raise DropExpiredError

        if drop.status == DropStatus.CONSUMED:
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="consumed").inc()
            raise DropConsumedError

        if drop.status != DropStatus.ACTIVE:
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_ready").inc()
            raise DropNotReadyError

        return drop

    async def get_admin_logs(self) -> dict[str, Any]:
        """Return recent activity for the public logs dashboard."""
        drops = await self._repository.get_all_drops(50)
        events = await self._repository.get_all_download_events(50)
        outbox_events = await self._outbox_repo.get_all_events(50)

        drop_map = {drop.id: drop for drop in drops}
        formatted_events = []
        for event in events:
            drop = drop_map.get(event.drop_id)
            formatted_events.append(
                {
                    "id": event.id,
                    "request_id": event.request_id,
                    "ip_address": event.ip_address,
                    "filename": drop.original_filename if drop else "Unknown",
                    "public_id": drop.public_id if drop else "Unknown",
                    "download_number": event.download_number,
                    "max_downloads": drop.max_downloads if drop else None,
                    "duration_ms": (
                        round(event.duration_ms, 2)
                        if event.duration_ms is not None
                        else None
                    ),
                    "created_at": (
                        event.created_at.isoformat() if event.created_at else None
                    ),
                }
            )

        return {
            "drops": [
                {
                    "public_id": drop.public_id,
                    "original_filename": drop.original_filename,
                    "size_bytes": drop.size_bytes,
                    "download_count": drop.download_count,
                    "max_downloads": drop.max_downloads,
                    "status": (
                        drop.status.value
                        if hasattr(drop.status, "value")
                        else str(drop.status)
                    ),
                    "created_at": (
                        drop.created_at.isoformat() if drop.created_at else None
                    ),
                    "expires_at": (
                        drop.expires_at.isoformat() if drop.expires_at else None
                    ),
                }
                for drop in drops
            ],
            "download_events": formatted_events,
            "tasks": [
                {
                    "id": str(task.id),
                    "event_type": task.event_type,
                    "status": (
                        task.status.value
                        if hasattr(task.status, "value")
                        else str(task.status)
                    ),
                    "payload": task.payload,
                    "created_at": (
                        task.created_at.isoformat() if task.created_at else None
                    ),
                    "processed_at": (
                        task.processed_at.isoformat() if task.processed_at else None
                    ),
                }
                for task in outbox_events
            ],
        }

    async def create(
        self,
        file: UploadFile,
        expires_in_seconds: int,
        max_downloads: int | None,
        request: Request | None = None,
    ) -> tuple[DropModel, str]:
        settings = get_settings()
        now = datetime.now(UTC)

        drop_id = uuid.uuid4()
        token = drop_id_var.set(str(drop_id))
        public_id = generate_public_id()
        access_token = generate_access_token()
        access_token_hash = compute_token_hash(access_token, settings.drop_token_pepper)
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
                    extra={
                        "size_bytes": size_bytes,
                        "max_size": settings.max_upload_size_bytes,
                    },
                )
                drop_id_var.reset(token)
                raise FileTooLargeError

        await file.seek(0)

        if request is not None and size_bytes > 0:
            await rate_limit_upload_bytes(request, cost=size_bytes)

        drop = DropModel(
            id=drop_id,
            public_id=public_id,
            access_token_hash=access_token_hash,
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

        return drop, access_token

    async def get_download_stream(
        self,
        public_id: str,
        access_token: str | None,
        session_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        duration_ms: float | None = None,
    ) -> tuple[Any, str, int, str | None]:
        drop = await self.verify_drop_access(public_id, access_token)
        settings = get_settings()
        now = datetime.now(UTC)

        session_hash = compute_session_hash(session_id, settings.session_pepper)

        (
            updated_drop,
            grant,
            is_new_grant,
        ) = await self._repository.acquire_download_grant(public_id, session_hash)

        if updated_drop is None or grant is None:
            if drop.expires_at <= now:
                DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="expired").inc()
                raise DropExpiredError
            if drop.status == DropStatus.CONSUMED:
                DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="consumed").inc()
                raise DropConsumedError
            DROP_DOWNLOADS_REJECTED_TOTAL.labels(reason="not_found").inc()
            raise DropNotFoundError

        if is_new_grant:
            DROP_DOWNLOADS_TOTAL.inc()
            DOWNLOAD_GRANTS_CREATED_TOTAL.inc()
        else:
            DOWNLOAD_GRANTS_REUSED_TOTAL.inc()

        pseudo_ip = (
            pseudonymize_ip(ip_address, settings.session_pepper) if ip_address else None
        )
        event = DownloadEventModel(
            drop_id=updated_drop.id,
            ip_address=pseudo_ip,
            user_agent=user_agent,
            request_id=request_id,
            download_number=updated_drop.download_count,
            duration_ms=duration_ms,
        )
        await self._repository.record_download_event(event)
        await self._session.commit()

        body, size, content_type = await run_in_threadpool(
            self._storage.get_object,
            updated_drop.storage_key,
        )

        return body, updated_drop.original_filename, size, content_type

    async def complete_download_grant(
        self,
        public_id: str,
        session_id: str,
    ) -> None:
        """Complete a stream and enqueue cleanup only after all grants finish."""
        settings = get_settings()
        session_hash = compute_session_hash(session_id, settings.session_pepper)
        result = await self._session.execute(
            select(DropModel).where(DropModel.public_id == public_id).with_for_update()
        )
        drop = result.scalar_one_or_none()
        if drop is None:
            return

        grant = await self._repository.get_download_grant(drop.id, session_hash)
        if grant is None or grant.status.value != "ACTIVE":
            return

        await self._repository.complete_download_grant(grant.id)
        if drop.status == DropStatus.CONSUMED:
            active_grants = await self._repository.count_active_grants(drop.id)
            if active_grants == 0:
                existing_event = await self._session.execute(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_type == "DROP_CLEANUP_REQUIRED",
                        OutboxEventModel.payload["drop_id"].as_string() == str(drop.id),
                    )
                )
                if existing_event.scalar_one_or_none() is None:
                    self._session.add(
                        OutboxEventModel(
                            event_type="DROP_CLEANUP_REQUIRED",
                            payload={"drop_id": str(drop.id)},
                            status=OutboxStatus.PENDING,
                        )
                    )

        await self._session.commit()

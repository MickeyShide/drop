import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from drop.config import get_settings
from drop.infrastructure.database.models import (
    DownloadEventModel,
    DownloadGrantModel,
    DropModel,
    DropStatus,
    GrantStatus,
)


class DropRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, drop: DropModel) -> DropModel:
        self._session.add(drop)
        await self._session.flush()
        return drop

    async def get_by_public_id(self, public_id: str) -> DropModel | None:
        stmt = select(DropModel).where(DropModel.public_id == public_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        drop_id: UUID,
    ) -> DropModel | None:
        return await self._session.get(DropModel, drop_id)

    async def get_download_grant(
        self,
        drop_id: UUID,
        session_hash: bytes,
    ) -> DownloadGrantModel | None:
        stmt = select(DownloadGrantModel).where(
            DownloadGrantModel.drop_id == drop_id,
            DownloadGrantModel.client_session_hash == session_hash,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def acquire_download_grant(
        self,
        public_id: str,
        session_hash: bytes,
    ) -> tuple[DropModel | None, DownloadGrantModel | None, bool]:
        """Acquire or reuse a download grant for a client session.

        Returns (drop, grant, is_new_grant_created).
        """
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(DropModel)
            .where(DropModel.public_id == public_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        drop = result.scalar_one_or_none()

        if drop is None:
            return None, None, False

        # If already expired or deleting/deleted/failed
        if drop.status in (
            DropStatus.EXPIRED,
            DropStatus.DELETING,
            DropStatus.DELETED,
            DropStatus.FAILED,
        ):
            return drop, None, False

        if drop.expires_at <= now:
            return drop, None, False

        # The row lock serializes all new grants for this Drop. The unique
        # constraint remains a second line of defense at the database level.
        existing_grant = await self.get_download_grant(drop.id, session_hash)
        if existing_grant is not None:
            if existing_grant.status == GrantStatus.EXPIRED or (
                existing_grant.expires_at is not None
                and existing_grant.expires_at <= now
                and existing_grant.status == GrantStatus.ACTIVE
            ):
                return drop, None, False
            # A Drop can be CONSUMED for new sessions, but an existing
            # recipient grant remains usable until cleanup removes the object.
            return drop, existing_grant, False

        # For NEW sessions, Drop MUST be ACTIVE
        if drop.status != DropStatus.ACTIVE:
            return drop, None, False

        if drop.max_downloads is not None and drop.download_count >= drop.max_downloads:
            return drop, None, False

        new_grant = DownloadGrantModel(
            id=uuid.uuid4(),
            drop_id=drop.id,
            client_session_hash=session_hash,
            status=GrantStatus.ACTIVE,
            created_at=now,
            expires_at=now
            + timedelta(seconds=get_settings().download_stream_lock_seconds),
        )
        self._session.add(new_grant)
        drop.download_count += 1
        if drop.max_downloads is not None and drop.download_count >= drop.max_downloads:
            drop.status = DropStatus.CONSUMED
            drop.consumed_at = now
        await self._session.flush()

        return drop, new_grant, True

    async def count_active_grants(
        self, drop_id: UUID, now: datetime | None = None
    ) -> int:
        cutoff = now or datetime.now(UTC)
        result = await self._session.execute(
            select(func.count(DownloadGrantModel.id)).where(
                DownloadGrantModel.drop_id == drop_id,
                DownloadGrantModel.status == GrantStatus.ACTIVE,
                (DownloadGrantModel.expires_at.is_(None))
                | (DownloadGrantModel.expires_at > cutoff),
            )
        )
        return int(result.scalar_one())

    async def expire_stale_grants(self, now: datetime | None = None) -> list[UUID]:
        cutoff = now or datetime.now(UTC)
        result = await self._session.execute(
            update(DownloadGrantModel)
            .where(
                DownloadGrantModel.status == GrantStatus.ACTIVE,
                DownloadGrantModel.expires_at.is_not(None),
                DownloadGrantModel.expires_at <= cutoff,
            )
            .values(status=GrantStatus.EXPIRED, completed_at=cutoff)
            .returning(DownloadGrantModel.drop_id)
        )
        return list(result.scalars().all())

    async def complete_download_grant(
        self,
        grant_id: UUID,
    ) -> None:
        now = datetime.now(UTC)
        stmt = (
            update(DownloadGrantModel)
            .where(DownloadGrantModel.id == grant_id)
            .values(
                status=GrantStatus.COMPLETED,
                completed_at=now,
            )
        )
        await self._session.execute(stmt)

    async def consume_download(
        self,
        public_id: str,
    ) -> DropModel | None:
        now = datetime.now(UTC)

        stmt = (
            update(DropModel)
            .where(
                DropModel.public_id == public_id,
                DropModel.status == DropStatus.ACTIVE,
                DropModel.expires_at > now,
                DropModel.max_downloads.is_(None)
                | (DropModel.download_count < DropModel.max_downloads),
            )
            .values(
                download_count=DropModel.download_count + 1,
                status=case(
                    (
                        DropModel.max_downloads.is_not(None)
                        & (DropModel.download_count + 1 >= DropModel.max_downloads),
                        DropStatus.CONSUMED,
                    ),
                    else_=DropModel.status,
                ),
                consumed_at=case(
                    (
                        DropModel.max_downloads.is_not(None)
                        & (DropModel.download_count + 1 >= DropModel.max_downloads),
                        now,
                    ),
                    else_=DropModel.consumed_at,
                ),
            )
            .returning(DropModel)
        )

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_expired_drops(
        self,
        now: datetime | None = None,
    ) -> list[DropModel]:
        cutoff = now or datetime.now(UTC)
        stmt = select(DropModel).where(
            DropModel.status == DropStatus.ACTIVE,
            DropModel.expires_at <= cutoff,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def record_download_event(self, event: DownloadEventModel) -> None:
        self._session.add(event)

    async def get_all_drops(self, limit: int = 50) -> list[DropModel]:
        stmt = select(DropModel).order_by(DropModel.created_at.desc()).limit(limit)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def get_all_download_events(
        self, limit: int = 50
    ) -> list[DownloadEventModel]:
        stmt = (
            select(DownloadEventModel)
            .order_by(DownloadEventModel.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

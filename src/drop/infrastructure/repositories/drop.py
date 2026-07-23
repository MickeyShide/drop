from click import UUID
from datetime import UTC, datetime

from sqlalchemy import select, update, case
from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.database.models import DropModel, DropStatus


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
            )
            .returning(DropModel)
        )

        result = await self._session.execute(stmt)

        return result.scalar_one_or_none()

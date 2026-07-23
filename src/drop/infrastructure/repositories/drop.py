from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.database.models import DropModel


class DropRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, drop: DropModel) -> DropModel:
        self._session.add(drop)
        await self._session.flush()

        return drop

    async def get_by_public_id(
        self,
        public_id: str,
    ) -> DropModel | None:
        stmt = select(DropModel).where(DropModel.public_id == public_id)

        result = await self._session.execute(stmt)

        return result.scalar_one_or_none()

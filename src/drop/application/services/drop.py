from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from drop.domain.exceptions import DropNotFoundError

from drop.application.schemas import CreateDropRequest
from drop.domain.public_id import generate_public_id
from drop.infrastructure.database.models import (
    DropModel,
    DropStatus,
)
from drop.infrastructure.repositories.drop import DropRepository


class DropService:
    def __init__(self, session: AsyncSession, repository: DropRepository) -> None:
        self._session = session
        self._repository = repository

    async def create(self, data: CreateDropRequest) -> DropModel:
        now = datetime.now(UTC)

        drop = DropModel(
            public_id=generate_public_id(),
            original_filename=data.original_filename,
            storage_key="pending",
            content_type=data.content_type,
            size_bytes=data.size_bytes,
            status=DropStatus.UPLOADING,
            max_downloads=data.max_downloads,
            download_count=0,
            expires_at=now + timedelta(seconds=data.expires_in_seconds),
            created_at=now,
        )

        await self._repository.add(drop)
        await self._session.commit()
        await self._session.refresh(drop)

        return drop

    async def get_by_public_id(self, public_id: str) -> DropModel:
        drop = await self._repository.get_by_public_id(public_id)
        if drop is None:
            raise DropNotFoundError
        return drop

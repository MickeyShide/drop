from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from drop.domain.public_id import generate_public_id
from drop.infrastructure.database.models import (
    DropModel,
    DropStatus,
)


async def create_active_drop(
    session: AsyncSession,
    *,
    max_downloads: int | None,
    expires_at: datetime | None = None,
) -> DropModel:
    now = datetime.now(UTC)

    drop = DropModel(
        public_id=generate_public_id(),
        original_filename="test.txt",
        storage_key="drops/test/source",
        content_type="text/plain",
        size_bytes=100,
        status=DropStatus.ACTIVE,
        max_downloads=max_downloads,
        download_count=0,
        expires_at=expires_at or (now + timedelta(hours=1)),
        created_at=now,
    )

    session.add(drop)
    await session.commit()
    await session.refresh(drop)

    return drop
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from drop.config import get_settings
from drop.domain.public_id import generate_public_id
from drop.domain.security import compute_token_hash, generate_access_token
from drop.infrastructure.database.models import (
    DropModel,
    DropStatus,
)


async def create_active_drop(
    session: AsyncSession,
    *,
    max_downloads: int | None,
    expires_at: datetime | None = None,
) -> tuple[DropModel, str]:
    now = datetime.now(UTC)
    access_token = generate_access_token()
    token_hash = compute_token_hash(access_token, get_settings().drop_token_pepper)

    drop = DropModel(
        public_id=generate_public_id(),
        access_token_hash=token_hash,
        original_filename="test.txt",
        storage_key=f"drops/{uuid.uuid4()}/source",
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

    return drop, access_token

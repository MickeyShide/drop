from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from drop.application.services.drop import DropService
from drop.infrastructure.database.engine import get_session
from drop.infrastructure.repositories.drop import DropRepository
from drop.infrastructure.storage.s3 import S3Storage

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_drop_service(session: SessionDep) -> DropService:
    repository = DropRepository(session)
    storage = S3Storage()

    return DropService(
        session=session,
        repository=repository,
        storage=storage,
    )


DropServiceDep = Annotated[DropService, Depends(get_drop_service)]

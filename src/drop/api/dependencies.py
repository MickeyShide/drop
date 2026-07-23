from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from drop.application.services.drop import DropService
from drop.infrastructure.database.engine import get_session
from drop.infrastructure.repositories.drop import DropRepository


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_drop_service(session: SessionDep) -> DropService:
    repository = DropRepository(session)
    return DropService(session=session, repository=repository)


DropServiceDep = Annotated[DropService, Depends(get_drop_service)]

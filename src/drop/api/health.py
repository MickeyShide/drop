from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.database.engine import get_session


router = APIRouter(tags=["health"])

SessionDep = Annotated[
    AsyncSession,
    Depends(get_session),
]


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(
    session: SessionDep,
) -> dict[str, str]:
    await session.execute(text("SELECT 1"))

    return {"status": "ready"}

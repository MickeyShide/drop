from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from drop.infrastructure.database.engine import get_session
from drop.infrastructure.redis import get_redis_client
from drop.infrastructure.storage.s3 import S3Storage

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
) -> dict[str, str | dict[str, str]]:
    checks: dict[str, str] = {}
    is_ready = True

    # 1. PostgreSQL check
    try:
        await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"failed: {e}"
        is_ready = False

    # 2. Redis check
    try:
        redis = get_redis_client()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"failed: {e}"
        is_ready = False

    # 3. MinIO (S3) check
    try:
        storage = S3Storage()
        await run_in_threadpool(storage._client.list_buckets)
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"failed: {e}"
        is_ready = False

    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}

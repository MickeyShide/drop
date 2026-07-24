import time
import urllib.parse
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from drop.api.dependencies import DropServiceDep
from drop.api.rate_limit import (
    rate_limit_create,
    rate_limit_download,
    rate_limit_download_per_drop,
    rate_limit_download_per_session,
    rate_limit_invalid_token,
    rate_limit_metadata,
)
from drop.application.schemas import CreateDropResponse, DropResponse, ErrorResponse
from drop.config import get_settings
from drop.domain.exceptions import DropNotFoundError
from drop.domain.security import compute_session_hash, generate_session_id
from drop.infrastructure.redis import get_redis_client
from drop.metrics import CONCURRENT_DOWNLOAD_REJECTED_TOTAL

router = APIRouter(prefix="/api/v1/drops", tags=["drops"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Bad Request / Validation Error"},
    404: {"model": ErrorResponse, "description": "Drop Not Found"},
    409: {
        "model": ErrorResponse,
        "description": "Drop Conflict / Download Already In Progress",
    },
    410: {"model": ErrorResponse, "description": "Drop Expired or Consumed"},
    413: {"model": ErrorResponse, "description": "Payload Too Large"},
    429: {"model": ErrorResponse, "description": "Too Many Requests"},
    500: {"model": ErrorResponse, "description": "Internal Server Error"},
    503: {"model": ErrorResponse, "description": "Service Unavailable"},
}


@router.post(
    "",
    response_model=CreateDropResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_create)],
    responses=ERROR_RESPONSES,
    summary="Create a new drop file",
)
async def create_drop(
    request: Request,
    service: DropServiceDep,
    file: Annotated[UploadFile, File()],
    expires_in_seconds: Annotated[int, Form(gt=0)],
    max_downloads: Annotated[int | None, Form(gt=0)] = None,
) -> CreateDropResponse:
    drop, access_token = await service.create(
        file=file,
        expires_in_seconds=expires_in_seconds,
        max_downloads=max_downloads,
        request=request,
    )

    host = request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto", "http")
    share_url = f"{scheme}://{host}/d/{drop.public_id}#{access_token}"

    return CreateDropResponse(
        public_id=drop.public_id,
        access_token=access_token,
        share_url=share_url,
        original_filename=drop.original_filename,
        content_type=drop.content_type,
        size_bytes=drop.size_bytes,
        status=drop.status.value,
        max_downloads=drop.max_downloads,
        download_count=drop.download_count,
        expires_at=drop.expires_at,
        created_at=drop.created_at,
    )


@router.get(
    "/logs/data",
    dependencies=[Depends(rate_limit_metadata)],
    responses=ERROR_RESPONSES,
    summary="Get public logs dashboard data",
)
async def get_logs_data(service: DropServiceDep) -> dict[str, Any]:
    """Return the data displayed by the public logs dashboard."""
    return await service.get_admin_logs()


@router.get(
    "/{public_id}",
    response_model=DropResponse,
    dependencies=[Depends(rate_limit_metadata)],
    responses=ERROR_RESPONSES,
    summary="Get drop metadata by public_id",
)
async def get_drop(
    public_id: str,
    request: Request,
    service: DropServiceDep,
    x_drop_token: Annotated[str | None, Header(alias="X-Drop-Token")] = None,
) -> DropResponse:
    """Safe GET endpoint for metadata ONLY.

    Never consumes a download slot, never creates a grant, and never triggers file deletion.
    """
    try:
        drop = await service.get_metadata(public_id, x_drop_token)
    except DropNotFoundError:
        await rate_limit_invalid_token(request)
        raise

    return DropResponse(
        public_id=drop.public_id,
        original_filename=drop.original_filename,
        content_type=drop.content_type,
        size_bytes=drop.size_bytes,
        status=drop.status.value,
        max_downloads=drop.max_downloads,
        download_count=drop.download_count,
        expires_at=drop.expires_at,
        created_at=drop.created_at,
    )


@router.post(
    "/{public_id}/download",
    dependencies=[Depends(rate_limit_download), Depends(rate_limit_download_per_drop)],
    responses=ERROR_RESPONSES,
    summary="Download drop file",
)
async def download_drop(
    public_id: str,
    request: Request,
    service: DropServiceDep,
    x_drop_token: Annotated[str | None, Header(alias="X-Drop-Token")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    x_drop_action: Annotated[str | None, Header(alias="X-Drop-Action")] = None,
) -> StreamingResponse:
    """Intentional download operation requiring capability access token and anonymous session.

    Uses drop_sid cookie for session unique download grants.
    """
    if x_drop_action != "download":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Drop-Action: download is required",
        )
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Idempotency-Key"
        )

    start_time = time.perf_counter()
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    request_id = getattr(request.state, "request_id", "unknown")

    session_id = request.cookies.get("drop_sid")
    new_session = False
    if not session_id:
        session_id = generate_session_id()
        new_session = True
    if len(session_id) > 512:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session cookie"
        )

    await rate_limit_download_per_session(request, session_id=session_id)

    # Redis concurrent stream lock protection per session
    settings = get_settings()
    session_hash = compute_session_hash(session_id, settings.session_pepper).hex()
    lock_key = f"download_stream:{public_id}:{session_hash}"
    redis = get_redis_client()
    try:
        locked = await redis.set(
            lock_key,
            request_id,
            nx=True,
            ex=settings.download_stream_lock_seconds,
        )
        if not locked:
            CONCURRENT_DOWNLOAD_REJECTED_TOTAL.inc()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Download is already in progress for this session",
            )
    except HTTPException:
        raise
    except Exception:
        # If Redis is down, fail closed for security protection
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stream lock service unavailable",
        )

    try:
        try:
            (
                body,
                filename,
                size_bytes,
                content_type,
            ) = await service.get_download_stream(
                public_id=public_id,
                access_token=x_drop_token,
                session_id=session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=idempotency_key or request_id,
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )
        except DropNotFoundError:
            await rate_limit_invalid_token(request)
            raise

        async def iterfile():
            try:
                while chunk := await run_in_threadpool(body.read, 1024 * 1024):
                    yield chunk
            finally:
                try:
                    close = getattr(body, "close", None)
                    if close is not None:
                        await run_in_threadpool(close)
                    await service.complete_download_grant(public_id, session_id)
                except Exception:
                    pass
                try:
                    await redis.delete(lock_key)
                except Exception:
                    pass

        encoded_filename = urllib.parse.quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(size_bytes),
            "X-Content-Type-Options": "nosniff",
        }

        stream_response = StreamingResponse(
            iterfile(),
            media_type=content_type or "application/octet-stream",
            headers=headers,
        )
        if new_session:
            is_secure = settings.session_cookie_secure
            if is_secure is None:
                is_secure = settings.app_env != "local"
            stream_response.set_cookie(
                key="drop_sid",
                value=session_id,
                httponly=True,
                samesite="strict",
                secure=is_secure,
                path="/",
            )
        return stream_response
    except Exception:
        try:
            await redis.delete(lock_key)
        except Exception:
            pass
        raise

from typing import Annotated, Any
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse

from drop.api.dependencies import DropServiceDep
from drop.api.rate_limit import RateLimitCreate, RateLimitDownload, RateLimitMetadata
from drop.application.schemas import DropResponse, ErrorResponse

router = APIRouter(prefix="/api/v1/drops", tags=["drops"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Bad Request / Validation Error"},
    404: {"model": ErrorResponse, "description": "Drop Not Found"},
    409: {"model": ErrorResponse, "description": "Drop Conflict / Not Ready"},
    410: {"model": ErrorResponse, "description": "Drop Expired or Consumed"},
    413: {"model": ErrorResponse, "description": "Payload Too Large"},
    429: {"model": ErrorResponse, "description": "Too Many Requests"},
    500: {"model": ErrorResponse, "description": "Internal Server Error"},
}


@router.post(
    "",
    response_model=DropResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimitCreate)],
    responses=ERROR_RESPONSES,
    summary="Create a new drop file",
)
async def create_drop(
    service: DropServiceDep,
    file: Annotated[UploadFile, File()],
    expires_in_seconds: Annotated[int, Form(gt=0)],
    max_downloads: Annotated[int | None, Form(gt=0)] = None,
) -> DropResponse:
    drop = await service.create(
        file=file,
        expires_in_seconds=expires_in_seconds,
        max_downloads=max_downloads,
    )

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


@router.get(
    "/{public_id}",
    response_model=DropResponse,
    dependencies=[Depends(RateLimitMetadata)],
    responses=ERROR_RESPONSES,
    summary="Get drop metadata by public_id",
)
async def get_drop(public_id: str, service: DropServiceDep) -> DropResponse:
    drop = await service.get_by_public_id(public_id)

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


@router.get(
    "/{public_id}/download",
    dependencies=[Depends(RateLimitDownload)],
    responses=ERROR_RESPONSES,
    summary="Download drop file",
)
async def download_drop(public_id: str, service: DropServiceDep) -> StreamingResponse:
    body, filename, size_bytes, content_type = await service.get_download_stream(public_id)

    def iterfile():
        while chunk := body.read(1024 * 1024):
            yield chunk

    encoded_filename = urllib.parse.quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}",
        "Content-Length": str(size_bytes),
    }

    return StreamingResponse(
        iterfile(),
        media_type=content_type or "application/octet-stream",
        headers=headers,
    )


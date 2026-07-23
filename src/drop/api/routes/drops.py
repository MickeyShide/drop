from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from drop.api.dependencies import DropServiceDep
from drop.api.rate_limit import RateLimitCreate, RateLimitDownload, RateLimitMetadata
from drop.application.schemas import DownloadResponse, DropResponse, ErrorResponse

router = APIRouter(prefix="/api/v1/drops", tags=["drops"])

ERROR_RESPONSES = {
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
    response_model=DownloadResponse,
    dependencies=[Depends(RateLimitDownload)],
    responses=ERROR_RESPONSES,
    summary="Get presigned download URL for drop",
)
async def download_drop(public_id: str, service: DropServiceDep) -> DownloadResponse:
    url = await service.get_download_url(public_id)

    return DownloadResponse(url=url, expires_in=60)

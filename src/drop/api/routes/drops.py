from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from drop.api.dependencies import DropServiceDep
from drop.application.schemas import DownloadResponse, DropResponse


router = APIRouter(prefix="/api/v1/drops", tags=["drops"])


@router.post("", response_model=DropResponse, status_code=status.HTTP_201_CREATED)
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


@router.get("/{public_id}", response_model=DropResponse)
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


@router.get("/{public_id}/download", response_model=DownloadResponse)
async def download_drop(public_id: str, service: DropServiceDep) -> DownloadResponse:
    url = await service.get_download_url(public_id)

    return DownloadResponse(url=url, expires_in=60)

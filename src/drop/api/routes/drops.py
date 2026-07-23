from drop.domain.exceptions import DropNotFoundError
from fastapi import APIRouter, status, HTTPException

from drop.api.dependencies import DropServiceDep
from drop.application.schemas import (
    CreateDropRequest,
    DropResponse,
)


router = APIRouter(prefix="/api/v1/drops", tags=["drops"])


@router.post("", response_model=DropResponse, status_code=status.HTTP_201_CREATED)
async def create_drop(data: CreateDropRequest, service: DropServiceDep) -> DropResponse:
    drop = await service.create(data)

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
    try:
        drop = await service.get_by_public_id(public_id)
    except DropNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Drop not found",
        ) from exc

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

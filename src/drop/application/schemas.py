from datetime import datetime

from pydantic import BaseModel


class DropResponse(BaseModel):
    public_id: str
    original_filename: str
    content_type: str | None
    size_bytes: int
    status: str
    max_downloads: int | None
    download_count: int
    expires_at: datetime
    created_at: datetime


class DownloadResponse(BaseModel):
    url: str
    expires_in: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | list | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


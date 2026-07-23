from datetime import datetime

from pydantic import BaseModel, Field


class CreateDropRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=255)
    size_bytes: int = Field(gt=0)
    expires_in_seconds: int = Field(gt=0)
    max_downloads: int | None = Field(default=None, gt=0)


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
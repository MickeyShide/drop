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
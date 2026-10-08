from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    original_filename: str
    content_type: str
    storage_key: str
    size_bytes: int
    status: DocumentStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    failure_reason: str | None

    model_config = ConfigDict(from_attributes=True)

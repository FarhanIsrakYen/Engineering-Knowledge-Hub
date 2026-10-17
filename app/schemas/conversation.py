from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.query import QuerySourceResponse


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("content")
    @classmethod
    def require_nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content cannot be empty")
        return value


class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    sources: list[QuerySourceResponse] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    model_config = ConfigDict(from_attributes=True)

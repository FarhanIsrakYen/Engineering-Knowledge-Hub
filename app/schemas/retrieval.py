from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=50)


class SearchResultResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    text: str
    page_number: int | None
    section_title: str | None
    score: float

    model_config = ConfigDict(from_attributes=True)

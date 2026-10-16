from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def require_nonempty_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question cannot be empty")
        return value


class QuerySourceResponse(BaseModel):
    document_id: UUID
    filename: str
    page: int | None
    chunk_id: UUID
    score: float

    model_config = ConfigDict(from_attributes=True)


class QueryResponse(BaseModel):
    answer: str
    sources: list[QuerySourceResponse]

    model_config = ConfigDict(from_attributes=True)

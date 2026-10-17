from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationDatasetItem(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    expected_answer: str = Field(min_length=1, max_length=12000)
    expected_document_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("question", "expected_answer")
    @classmethod
    def require_nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evaluation text cannot be empty")
        return value


class EvaluationCreate(BaseModel):
    workspace_id: UUID
    dataset: list[EvaluationDatasetItem] = Field(min_length=1, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=20)
    use_llm_judge: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "workspace_id": "8f01475e-bf86-4f76-b705-48fa9c54f911",
                    "dataset": [
                        {
                            "question": "What probe verifies PostgreSQL readiness?",
                            "expected_answer": "The API executes SELECT 1.",
                            "expected_document_ids": [
                                "f9a9ec26-b234-44eb-87d8-1b0c978f05f1"
                            ],
                        }
                    ],
                    "top_k": 5,
                    "use_llm_judge": False,
                }
            ]
        }
    )


class DeterministicMetricsResponse(BaseModel):
    hit_rate_at_k: float
    recall_at_k: float
    mrr: float


class SystemMetricsResponse(BaseModel):
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float


class LLMJudgeMetricsResponse(BaseModel):
    answer_relevance: float
    groundedness: float


class EvaluationMetricsResponse(BaseModel):
    deterministic: DeterministicMetricsResponse
    system: SystemMetricsResponse
    llm_judged: LLMJudgeMetricsResponse | None = None


class EvaluationResultResponse(BaseModel):
    item_index: int
    question: str
    expected_answer: str
    expected_document_ids: list[UUID]
    retrieved_document_ids: list[UUID]
    answer: str
    hit_rate_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    answer_relevance: float | None
    groundedness: float | None
    judge_reason: str | None

    model_config = ConfigDict(from_attributes=True)


class EvaluationRunResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    created_by: UUID | None
    status: Literal["running", "completed", "failed"]
    top_k: int
    llm_judge_enabled: bool
    item_count: int
    metrics: EvaluationMetricsResponse | None
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None
    results: list[EvaluationResultResponse]

    model_config = ConfigDict(from_attributes=True)

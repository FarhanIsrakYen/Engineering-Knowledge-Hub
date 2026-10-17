from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    hit_rate_at_k: float
    recall_at_k: float
    reciprocal_rank: float


def calculate_retrieval_metrics(
    expected_document_ids: list[UUID],
    retrieved_document_ids: list[UUID],
    k: int,
) -> RetrievalMetrics:
    if k < 1:
        raise ValueError("k must be at least 1")
    expected = set(expected_document_ids)
    if not expected:
        raise ValueError("expected_document_ids cannot be empty")

    ranked = retrieved_document_ids[:k]
    retrieved_relevant = expected.intersection(ranked)
    reciprocal_rank = next(
        (
            1.0 / rank
            for rank, document_id in enumerate(ranked, start=1)
            if document_id in expected
        ),
        0.0,
    )
    return RetrievalMetrics(
        hit_rate_at_k=1.0 if retrieved_relevant else 0.0,
        recall_at_k=len(retrieved_relevant) / len(expected),
        reciprocal_rank=reciprocal_rank,
    )


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot calculate a mean for an empty collection")
    return sum(values) / len(values)

from uuid import uuid4

import pytest

from app.evaluation.metrics import calculate_retrieval_metrics


def test_retrieval_metrics_for_first_rank_hit() -> None:
    expected = uuid4()

    metrics = calculate_retrieval_metrics(
        [expected],
        [expected, uuid4()],
        k=2,
    )

    assert metrics.hit_rate_at_k == 1.0
    assert metrics.recall_at_k == 1.0
    assert metrics.reciprocal_rank == 1.0


def test_retrieval_metrics_measure_partial_recall_and_rank() -> None:
    first_expected = uuid4()
    second_expected = uuid4()

    metrics = calculate_retrieval_metrics(
        [first_expected, second_expected],
        [uuid4(), second_expected, uuid4()],
        k=3,
    )

    assert metrics.hit_rate_at_k == 1.0
    assert metrics.recall_at_k == 0.5
    assert metrics.reciprocal_rank == 0.5


def test_retrieval_metrics_respect_k_cutoff() -> None:
    expected = uuid4()

    metrics = calculate_retrieval_metrics(
        [expected],
        [uuid4(), expected],
        k=1,
    )

    assert metrics.hit_rate_at_k == 0.0
    assert metrics.recall_at_k == 0.0
    assert metrics.reciprocal_rank == 0.0


def test_retrieval_metrics_do_not_double_count_duplicate_results() -> None:
    expected = uuid4()

    metrics = calculate_retrieval_metrics(
        [expected],
        [expected, expected],
        k=2,
    )

    assert metrics.recall_at_k == 1.0


def test_retrieval_metrics_require_expected_documents() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        calculate_retrieval_metrics([], [uuid4()], k=1)

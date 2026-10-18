import json
import logging

from app.core.logging import JsonFormatter


def test_retrieval_diagnostics_are_structured() -> None:
    record = logging.LogRecord(
        name="app.services.retrieval",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Retrieval completed",
        args=(),
        exc_info=None,
    )
    record.retrieval_mode = "hybrid"
    record.candidate_count = 7
    record.retrieval_latency_ms = 12.5

    payload = json.loads(JsonFormatter().format(record))

    assert payload["retrieval_mode"] == "hybrid"
    assert payload["candidate_count"] == 7
    assert payload["retrieval_latency_ms"] == 12.5


def test_query_stage_timings_are_structured() -> None:
    record = logging.LogRecord(
        name="app.services.query",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="RAG query completed",
        args=(),
        exc_info=None,
    )
    record.query_rewrite_latency_ms = 2.0
    record.query_retrieval_latency_ms = 14.0
    record.rerank_latency_ms = 8.0
    record.generation_latency_ms = 30.0
    record.query_total_latency_ms = 54.0
    record.final_context_count = 5

    payload = json.loads(JsonFormatter().format(record))

    assert payload["query_rewrite_latency_ms"] == 2.0
    assert payload["query_retrieval_latency_ms"] == 14.0
    assert payload["rerank_latency_ms"] == 8.0
    assert payload["generation_latency_ms"] == 30.0
    assert payload["query_total_latency_ms"] == 54.0
    assert payload["final_context_count"] == 5

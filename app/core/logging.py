import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig
from typing import Any

from app.core.request_context import get_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if request_id := get_request_id():
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if environment := getattr(record, "environment", None):
            payload["environment"] = environment
        for field in (
            "retrieval_mode",
            "candidate_count",
            "retrieval_latency_ms",
            "query_rewrite_latency_ms",
            "query_retrieval_latency_ms",
            "rerank_latency_ms",
            "generation_latency_ms",
            "query_total_latency_ms",
            "final_context_count",
            "conversation_id",
            "document_id",
            "http_method",
            "http_route",
            "http_status_code",
            "request_duration_ms",
            "cache_event",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, default=str)


def configure_logging(log_level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["default"], "level": log_level},
            "loggers": {
                "uvicorn.error": {"handlers": ["default"], "propagate": False},
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
        }
    )

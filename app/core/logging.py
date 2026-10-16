from datetime import UTC, datetime
import json
import logging
from logging.config import dictConfig
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
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
                "uvicorn.access": {"handlers": ["default"], "propagate": False},
            },
        }
    )

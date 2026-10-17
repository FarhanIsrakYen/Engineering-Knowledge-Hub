from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "ekh_http_requests_total",
    "HTTP requests completed",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "ekh_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("method", "route"),
)
RAG_QUERY_DURATION = Histogram(
    "ekh_rag_query_duration_seconds",
    "End-to-end RAG query duration in seconds",
)
RETRIEVAL_DURATION = Histogram(
    "ekh_retrieval_duration_seconds",
    "Retrieval duration in seconds",
    ("mode",),
)
GENERATION_DURATION = Histogram(
    "ekh_generation_duration_seconds",
    "LLM generation duration in seconds",
)
INGESTIONS = Counter(
    "ekh_ingestions_total",
    "Document ingestion outcomes",
    ("outcome",),
)
INGESTION_FAILURES = Counter(
    "ekh_ingestion_failures_total",
    "Document ingestion failures",
)

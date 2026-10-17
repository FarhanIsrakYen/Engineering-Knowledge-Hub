import logging
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS
from app.core.request_context import reset_request_id, set_request_id

logger = logging.getLogger(__name__)
REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestObservabilityMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._request_id(scope)
        token = set_request_id(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append(
                    (REQUEST_ID_HEADER.lower().encode(), request_id.encode())
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration = perf_counter() - started_at
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope.get("method", "UNKNOWN")
            HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method, route).observe(duration)
            logger.info(
                "HTTP request completed",
                extra={
                    "http_method": method,
                    "http_route": route,
                    "http_status_code": status_code,
                    "request_duration_ms": round(duration * 1000, 2),
                },
            )
            reset_request_id(token)

    @staticmethod
    def _request_id(scope: dict[str, Any]) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                candidate = value.decode("ascii", errors="ignore")
                if _SAFE_REQUEST_ID.fullmatch(candidate):
                    return candidate
                break
        return str(uuid4())

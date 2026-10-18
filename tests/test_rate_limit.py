from types import SimpleNamespace
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import (
    enforce_expensive_query_rate_limit,
    get_current_user,
)
from app.core.config import Settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestObservabilityMiddleware
from app.services.rate_limit import RateLimitResult


class CountingRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        del key, window_seconds
        self.calls += 1
        return RateLimitResult(
            allowed=self.calls <= limit,
            retry_after_seconds=37,
        )


def test_expensive_query_rate_limit_returns_429() -> None:
    application = FastAPI()
    application.state.settings = Settings(
        environment="test",
        query_rate_limit_requests=2,
        _env_file=None,
    )
    limiter = CountingRateLimiter()
    application.state.rate_limiter = limiter
    application.add_middleware(RequestObservabilityMiddleware)
    register_exception_handlers(application)

    async def current_user() -> SimpleNamespace:
        return SimpleNamespace(id=uuid4())

    application.dependency_overrides[get_current_user] = current_user

    @application.post(
        "/expensive",
        dependencies=[Depends(enforce_expensive_query_rate_limit)],
    )
    async def expensive() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(application) as client:
        assert client.post("/expensive").status_code == 200
        assert client.post("/expensive").status_code == 200
        response = client.post("/expensive")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "37"
    assert response.json() == {
        "error": {
            "code": "rate_limit_exceeded",
            "message": "Query rate limit exceeded",
        }
    }

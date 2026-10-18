from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(environment="test", _env_file=None)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_endpoints_return_ok(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_is_returned_and_preserved(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "deploy-42"})

    assert response.headers["X-Request-ID"] == "deploy-42"


def test_unsafe_request_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"X-Request-ID": "unsafe request id"},
    )

    request_id = response.headers["X-Request-ID"]
    assert request_id != "unsafe request id"
    assert len(request_id) == 36


def test_metrics_endpoint_is_prometheus_compatible(client: TestClient) -> None:
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "ekh_http_requests_total" in response.text

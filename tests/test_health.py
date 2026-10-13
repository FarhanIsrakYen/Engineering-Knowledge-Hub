from collections.abc import Iterator

from fastapi.testclient import TestClient
import pytest

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

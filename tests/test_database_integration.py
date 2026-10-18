import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.queue import InMemoryIngestionQueue
from tests.storage import InMemoryObjectStorage
from tests.vector_store import InMemoryVectorStore


@pytest.fixture
def database_client() -> Iterator[TestClient]:
    database_url = os.getenv("EKH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("EKH_TEST_DATABASE_URL is required for database integration tests")

    settings = Settings(
        environment="test",
        database_url=database_url,
        _env_file=None,
    )
    with TestClient(
        create_app(
            settings,
            object_storage=InMemoryObjectStorage(),
            ingestion_queue=InMemoryIngestionQueue(),
            vector_store=InMemoryVectorStore(),
        )
    ) as test_client:
        yield test_client


@pytest.mark.integration
def test_readiness_connects_to_postgresql(database_client: TestClient) -> None:
    response = database_client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "object_storage": "ok",
            "ingestion_queue": "ok",
            "vector_store": "ok",
            "redis": "ok",
        },
    }

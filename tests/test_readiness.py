from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from tests.storage import InMemoryObjectStorage
from tests.queue import InMemoryIngestionQueue
from tests.vector_store import InMemoryVectorStore


def test_readiness_returns_service_unavailable_when_database_fails() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = SQLAlchemyError("connection failed")

    async def unavailable_session() -> AsyncIterator[AsyncSession]:
        yield session

    application = create_app(
        Settings(environment="test", _env_file=None),
        object_storage=InMemoryObjectStorage(),
        ingestion_queue=InMemoryIngestionQueue(),
        vector_store=InMemoryVectorStore(),
    )
    application.dependency_overrides[get_db_session] = unavailable_session

    with TestClient(application) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "Database is unavailable",
        }
    }


def test_readiness_returns_service_unavailable_when_storage_fails() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalar_one.return_value = 1
    session.execute.return_value = result

    async def available_session() -> AsyncIterator[AsyncSession]:
        yield session

    application = create_app(
        Settings(environment="test", _env_file=None),
        object_storage=InMemoryObjectStorage(available=False),
        ingestion_queue=InMemoryIngestionQueue(),
        vector_store=InMemoryVectorStore(),
    )
    application.dependency_overrides[get_db_session] = available_session

    with TestClient(application) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "object_storage_unavailable",
            "message": "Object storage is unavailable",
        }
    }


def test_readiness_returns_service_unavailable_when_queue_fails() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalar_one.return_value = 1
    session.execute.return_value = result

    async def available_session() -> AsyncIterator[AsyncSession]:
        yield session

    application = create_app(
        Settings(environment="test", _env_file=None),
        object_storage=InMemoryObjectStorage(),
        ingestion_queue=InMemoryIngestionQueue(available=False),
        vector_store=InMemoryVectorStore(),
    )
    application.dependency_overrides[get_db_session] = available_session

    with TestClient(application) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "ingestion_queue_unavailable",
            "message": "Ingestion queue is unavailable",
        }
    }


def test_readiness_returns_service_unavailable_when_vector_store_fails() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.scalar_one.return_value = 1
    session.execute.return_value = result

    async def available_session() -> AsyncIterator[AsyncSession]:
        yield session

    application = create_app(
        Settings(environment="test", _env_file=None),
        object_storage=InMemoryObjectStorage(),
        ingestion_queue=InMemoryIngestionQueue(),
        vector_store=InMemoryVectorStore(available=False),
    )
    application.dependency_overrides[get_db_session] = available_session

    with TestClient(application) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "vector_store_unavailable",
            "message": "Vector store is unavailable",
        }
    }

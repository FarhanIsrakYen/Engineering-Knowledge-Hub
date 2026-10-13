import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
import os
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.main import create_app
from app.services.ingestion import ingest_document
from tests.embeddings import DeterministicEmbeddingProvider
from tests.queue import InMemoryIngestionQueue
from tests.storage import InMemoryObjectStorage
from tests.vector_store import InMemoryVectorStore


@dataclass(frozen=True, slots=True)
class RetrievalTestContext:
    client: TestClient
    settings: Settings
    storage: InMemoryObjectStorage
    embedding_provider: DeterministicEmbeddingProvider
    vector_store: InMemoryVectorStore


@pytest.fixture
def retrieval_context() -> Iterator[RetrievalTestContext]:
    database_url = os.getenv("EKH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("EKH_TEST_DATABASE_URL is required for retrieval tests")

    settings = Settings(
        environment="test",
        database_url=database_url,
        document_chunk_size=500,
        document_chunk_overlap=50,
        embedding_dimensions=3,
        _env_file=None,
    )
    storage = InMemoryObjectStorage()
    embedding_provider = DeterministicEmbeddingProvider()
    vector_store = InMemoryVectorStore()
    with TestClient(
        create_app(
            settings,
            object_storage=storage,
            ingestion_queue=InMemoryIngestionQueue(),
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )
    ) as client:
        yield RetrievalTestContext(
            client=client,
            settings=settings,
            storage=storage,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )


def _create_workspace(
    client: TestClient,
    label: str,
) -> tuple[dict[str, str], UUID, UUID]:
    email = f"retrieval-{label}-{uuid4().hex}@example.com"
    password = "correct horse battery staple"
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Retrieval Tester",
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    organization = client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": f"{label} Org", "slug": f"{label}-{uuid4().hex}"},
    )
    workspace = client.post(
        f"/api/v1/organizations/{organization.json()['id']}/workspaces",
        headers=headers,
        json={"name": f"{label} Workspace"},
    )
    return (
        headers,
        UUID(organization.json()["id"]),
        UUID(workspace.json()["id"]),
    )


def _upload(
    context: RetrievalTestContext,
    headers: dict[str, str],
    workspace_id: UUID,
    filename: str,
    content: bytes,
) -> UUID:
    response = context.client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        headers=headers,
        files={"file": (filename, content, "text/plain")},
    )
    assert response.status_code == 202
    return UUID(response.json()["id"])


async def _ingest(
    context: RetrievalTestContext,
    document_ids: list[UUID],
) -> None:
    engine = create_database_engine(context.settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        for document_id in document_ids:
            await ingest_document(
                session_factory,
                context.storage,
                context.embedding_provider,
                context.vector_store,
                document_id,
                chunk_size=context.settings.document_chunk_size,
                chunk_overlap=context.settings.document_chunk_overlap,
                embedding_dimensions=context.settings.embedding_dimensions,
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_search_returns_ranked_chunks_and_filters_tenants(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, organization_id, workspace_id = _create_workspace(
        retrieval_context.client,
        "primary",
    )
    other_headers, _, other_workspace_id = _create_workspace(
        retrieval_context.client,
        "other",
    )
    postgres_document = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "postgres.txt",
        b"PostgreSQL is the durable relational database for application data.",
    )
    redis_document = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "redis.txt",
        b"Redis is used as a fast cache and task broker.",
    )
    other_document = _upload(
        retrieval_context,
        other_headers,
        other_workspace_id,
        "private.txt",
        b"PostgreSQL private tenant database secrets.",
    )
    asyncio.run(
        _ingest(
            retrieval_context,
            [postgres_document, redis_document, other_document],
        )
    )

    response = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/search",
        headers=headers,
        json={"query": "Which database stores durable data?", "limit": 5},
    )

    assert response.status_code == 200
    results = response.json()
    assert results[0]["document_id"] == str(postgres_document)
    assert {item["document_id"] for item in results} == {
        str(postgres_document),
        str(redis_document),
    }
    assert all(item["document_id"] != str(other_document) for item in results)
    assert retrieval_context.vector_store.search_filters[-1] == (
        organization_id,
        workspace_id,
    )

    cross_tenant = retrieval_context.client.post(
        f"/api/v1/workspaces/{other_workspace_id}/search",
        headers=headers,
        json={"query": "private database", "limit": 5},
    )
    assert cross_tenant.status_code == 404

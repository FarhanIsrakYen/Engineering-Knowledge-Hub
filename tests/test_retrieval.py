import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.main import create_app
from app.services.ingestion import ingest_document
from app.services.retrieval import (
    RetrievalMode,
    RetrievalService,
    RetrievedChunk,
)
from tests.embeddings import DeterministicEmbeddingProvider
from tests.llm import FakeLLMProvider
from tests.queue import InMemoryIngestionQueue
from tests.rag import FakeQueryRewriter, FakeReranker
from tests.storage import InMemoryObjectStorage
from tests.vector_store import InMemoryVectorStore


@dataclass(frozen=True, slots=True)
class RetrievalTestContext:
    client: TestClient
    settings: Settings
    storage: InMemoryObjectStorage
    embedding_provider: DeterministicEmbeddingProvider
    vector_store: InMemoryVectorStore
    llm_provider: FakeLLMProvider
    query_rewriter: FakeQueryRewriter
    reranker: FakeReranker


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
    llm_provider = FakeLLMProvider()
    query_rewriter = FakeQueryRewriter()
    reranker = FakeReranker()
    with TestClient(
        create_app(
            settings,
            object_storage=storage,
            ingestion_queue=InMemoryIngestionQueue(),
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm_provider,
            query_rewriter=query_rewriter,
            reranker=reranker,
        )
    ) as client:
        yield RetrievalTestContext(
            client=client,
            settings=settings,
            storage=storage,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            llm_provider=llm_provider,
            query_rewriter=query_rewriter,
            reranker=reranker,
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


async def _search(
    context: RetrievalTestContext,
    workspace_id: UUID,
    query: str,
    limit: int,
    mode: RetrievalMode,
) -> list[RetrievedChunk]:
    engine = create_database_engine(context.settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            return await RetrievalService(
                session,
                context.embedding_provider,
                context.vector_store,
                mode,
            ).search(workspace_id, query, limit)
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


@pytest.mark.integration
def test_hybrid_search_promotes_exact_technical_identifier(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "hybrid-identifier",
    )
    first_distractor = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "general.txt",
        b"General deployment guidance for routine application operations.",
    )
    second_distractor = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "overview.txt",
        b"An overview of service monitoring and operational procedures.",
    )
    identifier_document = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "incident.txt",
        b"Incident ZXQ4821 requires restarting the edge gateway.",
    )
    asyncio.run(
        _ingest(
            retrieval_context,
            [first_distractor, second_distractor, identifier_document],
        )
    )

    vector_results = asyncio.run(
        _search(
            retrieval_context,
            workspace_id,
            "ZXQ4821",
            3,
            "vector",
        )
    )
    hybrid_results = asyncio.run(
        _search(
            retrieval_context,
            workspace_id,
            "ZXQ4821",
            3,
            "hybrid",
        )
    )

    assert vector_results[0].document_id != identifier_document
    assert hybrid_results[0].document_id == identifier_document
    assert hybrid_results[0].matched_lexically is True


@pytest.mark.integration
def test_query_returns_grounded_answer_and_sources(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "query-success",
    )
    document_id = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "postgres.txt",
        b"PostgreSQL is the durable relational database for application data.",
    )
    asyncio.run(_ingest(retrieval_context, [document_id]))

    response = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/query",
        headers=headers,
        json={"question": "Which PostgreSQL database stores data?", "top_k": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "PostgreSQL stores durable application data [S1]."
    assert len(body["sources"]) == 1
    assert body["sources"][0]["document_id"] == str(document_id)
    assert body["sources"][0]["filename"] == "postgres.txt"
    assert body["sources"][0]["page"] is None
    assert body["sources"][0]["score"] > 0
    system_prompt, user_prompt = retrieval_context.llm_provider.calls[-1]
    assert "only the supplied source context" in system_prompt
    assert "[S1]" in user_prompt
    assert "postgres.txt" in user_prompt


@pytest.mark.integration
def test_query_returns_insufficient_context_without_calling_llm(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "query-no-context",
    )
    document_id = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "postgres.txt",
        b"PostgreSQL is the durable relational database for application data.",
    )
    asyncio.run(_ingest(retrieval_context, [document_id]))

    response = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/query",
        headers=headers,
        json={"question": "How do solar panels generate electricity?"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": (
            "The available workspace context is insufficient to answer "
            "this question."
        ),
        "sources": [],
    }
    assert retrieval_context.llm_provider.calls == []


@pytest.mark.integration
def test_query_rejects_cross_tenant_workspace_access(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, _ = _create_workspace(
        retrieval_context.client,
        "query-owner",
    )
    _, _, other_workspace_id = _create_workspace(
        retrieval_context.client,
        "query-other",
    )

    response = retrieval_context.client.post(
        f"/api/v1/workspaces/{other_workspace_id}/query",
        headers=headers,
        json={"question": "What is private?"},
    )

    assert response.status_code == 404
    assert retrieval_context.llm_provider.calls == []


@pytest.mark.integration
def test_query_maps_llm_provider_failure_to_service_unavailable(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "query-failure",
    )
    document_id = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "postgres.txt",
        b"PostgreSQL is the durable relational database for application data.",
    )
    asyncio.run(_ingest(retrieval_context, [document_id]))
    retrieval_context.llm_provider.fail = True

    response = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/query",
        headers=headers,
        json={"question": "Which PostgreSQL database stores data?"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "llm_provider_unavailable",
            "message": "The answer generation service is unavailable",
        }
    }


@pytest.mark.integration
def test_create_and_read_conversation(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "conversation-create",
    )

    created = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations",
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["workspace_id"] == str(workspace_id)
    assert created.json()["messages"] == []

    fetched = retrieval_context.client.get(
        f"/api/v1/conversations/{created.json()['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json() == created.json()


@pytest.mark.integration
def test_streamed_conversation_message_persists_answer_and_sources(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "conversation-stream",
    )
    document_id = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "postgres.txt",
        b"PostgreSQL is the durable relational database for application data.",
    )
    asyncio.run(_ingest(retrieval_context, [document_id]))
    conversation = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations",
        headers=headers,
    ).json()

    response = retrieval_context.client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=headers,
        json={"content": "Which PostgreSQL database stores data?", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert "event: sources" in response.text
    assert "event: done" in response.text

    fetched = retrieval_context.client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=headers,
    )
    messages = fetched.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == retrieval_context.llm_provider.response
    assert messages[1]["sources"][0]["document_id"] == str(document_id)


@pytest.mark.integration
def test_follow_up_uses_bounded_history_only_for_query_interpretation(
    retrieval_context: RetrievalTestContext,
) -> None:
    headers, _, workspace_id = _create_workspace(
        retrieval_context.client,
        "conversation-follow-up",
    )
    document_id = _upload(
        retrieval_context,
        headers,
        workspace_id,
        "postgres.txt",
        b"PostgreSQL is the durable relational database for application data.",
    )
    asyncio.run(_ingest(retrieval_context, [document_id]))
    conversation = retrieval_context.client.post(
        f"/api/v1/workspaces/{workspace_id}/conversations",
        headers=headers,
    ).json()
    retrieval_context.llm_provider.response = "HISTORY_ONLY_MARKER [S1]."
    first = retrieval_context.client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=headers,
        json={"content": "Tell me about PostgreSQL."},
    )
    assert first.status_code == 200

    retrieval_context.query_rewriter.rewritten_query = (
        "PostgreSQL database durability"
    )
    retrieval_context.llm_provider.response = "It stores durable data [S1]."
    second = retrieval_context.client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=headers,
        json={"content": "What about its durability?"},
    )

    assert second.status_code == 200
    question, history = retrieval_context.query_rewriter.calls[-1]
    assert question == "What about its durability?"
    assert history is not None
    assert [turn.role for turn in history] == ["user", "assistant"]
    _, generation_prompt = retrieval_context.llm_provider.stream_calls[-1]
    assert "What about its durability?" in generation_prompt
    assert "PostgreSQL database durability" in generation_prompt
    assert "HISTORY_ONLY_MARKER" not in generation_prompt


@pytest.mark.integration
def test_conversation_is_hidden_from_other_tenant(
    retrieval_context: RetrievalTestContext,
) -> None:
    owner_headers, _, owner_workspace_id = _create_workspace(
        retrieval_context.client,
        "conversation-owner",
    )
    other_headers, _, _ = _create_workspace(
        retrieval_context.client,
        "conversation-outsider",
    )
    conversation = retrieval_context.client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/conversations",
        headers=owner_headers,
    ).json()

    get_attempt = retrieval_context.client.get(
        f"/api/v1/conversations/{conversation['id']}",
        headers=other_headers,
    )
    message_attempt = retrieval_context.client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=other_headers,
        json={"content": "Show me private context"},
    )

    assert get_attempt.status_code == 404
    assert message_attempt.status_code == 404

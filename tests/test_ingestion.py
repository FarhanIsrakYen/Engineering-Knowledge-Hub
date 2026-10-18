import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.ingestion.parsers import DocumentParsingError, get_parser
from app.main import create_app
from app.models.document import Document, DocumentChunk
from app.services.ingestion import ingest_document
from tests.embeddings import DeterministicEmbeddingProvider
from tests.queue import InMemoryIngestionQueue
from tests.storage import InMemoryObjectStorage
from tests.vector_store import InMemoryVectorStore


class ObservingObjectStorage(InMemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.session_factory: async_sessionmaker[AsyncSession] | None = None
        self.statuses_at_download: list[str] = []

    async def download_file(self, storage_key: str) -> bytes:
        assert self.session_factory is not None
        document_id = UUID(storage_key.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        async with self.session_factory() as session:
            status = await session.scalar(
                select(Document.status).where(Document.id == document_id)
            )
        assert status is not None
        self.statuses_at_download.append(status)
        return await super().download_file(storage_key)


@dataclass(frozen=True, slots=True)
class IngestionTestContext:
    client: TestClient
    settings: Settings
    storage: ObservingObjectStorage
    embedding_provider: DeterministicEmbeddingProvider
    vector_store: InMemoryVectorStore


@pytest.fixture
def ingestion_context() -> Iterator[IngestionTestContext]:
    database_url = os.getenv("EKH_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("EKH_TEST_DATABASE_URL is required for ingestion tests")

    settings = Settings(
        environment="test",
        database_url=database_url,
        jwt_secret="test-only-jwt-secret-with-at-least-32-characters",
        document_max_upload_bytes=4096,
        document_chunk_size=80,
        document_chunk_overlap=10,
        embedding_dimensions=3,
        _env_file=None,
    )
    storage = ObservingObjectStorage()
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
        yield IngestionTestContext(
            client=client,
            settings=settings,
            storage=storage,
            embedding_provider=embedding_provider,
            vector_store=vector_store,
        )


def _create_document(
    context: IngestionTestContext,
    *,
    filename: str,
    content: bytes,
    content_type: str,
) -> dict:
    label = uuid4().hex
    password = "correct horse battery staple"
    registration = context.client.post(
        "/api/v1/auth/register",
        json={
            "email": f"ingestion-{label}@example.com",
            "password": password,
            "display_name": "Ingestion Tester",
        },
    )
    assert registration.status_code == 201
    login = context.client.post(
        "/api/v1/auth/login",
        json={
            "email": f"ingestion-{label}@example.com",
            "password": password,
        },
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    organization = context.client.post(
        "/api/v1/organizations",
        headers=headers,
        json={"name": "Ingestion Org", "slug": f"ingestion-{label}"},
    )
    workspace = context.client.post(
        f"/api/v1/organizations/{organization.json()['id']}/workspaces",
        headers=headers,
        json={"name": "Ingestion Workspace"},
    )
    upload = context.client.post(
        f"/api/v1/workspaces/{workspace.json()['id']}/documents",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )
    assert upload.status_code == 202
    return upload.json()


async def _run_and_read(
    context: IngestionTestContext,
    document_id: UUID,
) -> tuple[Document, list[DocumentChunk]]:
    engine = create_database_engine(context.settings.database_url)
    session_factory = create_session_factory(engine)
    context.storage.session_factory = session_factory
    try:
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
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            chunks = list(
                await session.scalars(
                    select(DocumentChunk)
                    .where(DocumentChunk.document_id == document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            )
            assert document is not None
            return document, chunks
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_ingestion_creates_chunks_tracks_status_and_is_idempotent(
    ingestion_context: IngestionTestContext,
) -> None:
    content = (
        b"# Architecture\n"
        + b"Services communicate through explicit boundaries. " * 8
    )
    uploaded = _create_document(
        ingestion_context,
        filename="architecture.md",
        content=content,
        content_type="text/markdown",
    )
    assert uploaded["status"] == "pending"
    document_id = UUID(uploaded["id"])

    document, first_chunks = asyncio.run(
        _run_and_read(ingestion_context, document_id)
    )

    assert ingestion_context.storage.statuses_at_download == ["processing"]
    assert document.status == "ready"
    assert document.failure_reason is None
    assert len(first_chunks) > 1
    assert [chunk.chunk_index for chunk in first_chunks] == list(
        range(len(first_chunks))
    )
    assert {chunk.document_id for chunk in first_chunks} == {document_id}
    assert {chunk.section_title for chunk in first_chunks} == {"Architecture"}
    assert all(len(chunk.text) <= 80 for chunk in first_chunks)
    indexed_points = list(ingestion_context.vector_store.points.values())
    assert len(indexed_points) == len(first_chunks)
    assert {
        point.payload["document_id"] for point in indexed_points
    } == {str(document_id)}
    assert all(
        {
            "organization_id",
            "workspace_id",
            "document_id",
            "chunk_id",
            "chunk_index",
        }
        <= point.payload.keys()
        for point in indexed_points
    )
    first_values = [
        (chunk.chunk_index, chunk.text, chunk.section_title)
        for chunk in first_chunks
    ]

    retried_document, retried_chunks = asyncio.run(
        _run_and_read(ingestion_context, document_id)
    )

    assert retried_document.status == "ready"
    assert ingestion_context.storage.statuses_at_download == ["processing"]
    assert [
        (chunk.chunk_index, chunk.text, chunk.section_title)
        for chunk in retried_chunks
    ] == first_values


@pytest.mark.integration
def test_failed_parsing_sets_failure_status_and_reason(
    ingestion_context: IngestionTestContext,
) -> None:
    uploaded = _create_document(
        ingestion_context,
        filename="broken.pdf",
        content=b"this is not a PDF",
        content_type="application/pdf",
    )

    document, chunks = asyncio.run(
        _run_and_read(ingestion_context, UUID(uploaded["id"]))
    )

    assert document.status == "failed"
    assert document.failure_reason == "The PDF could not be parsed"
    assert chunks == []
    assert ingestion_context.storage.statuses_at_download == ["processing"]


@pytest.mark.integration
def test_embedding_failure_marks_document_failed_without_vectors(
    ingestion_context: IngestionTestContext,
) -> None:
    ingestion_context.embedding_provider.fail = True
    uploaded = _create_document(
        ingestion_context,
        filename="embedding.txt",
        content=b"PostgreSQL stores durable application data.",
        content_type="text/plain",
    )

    document, chunks = asyncio.run(
        _run_and_read(ingestion_context, UUID(uploaded["id"]))
    )

    assert document.status == "failed"
    assert document.failure_reason == "Embedding generation failed"
    assert chunks == []
    assert ingestion_context.vector_store.points == {}


def test_plain_text_parser_rejects_non_utf8_input() -> None:
    parser = get_parser("text/plain")

    with pytest.raises(DocumentParsingError, match="not valid UTF-8"):
        parser.parse(b"\xff\xfe")


def test_pdf_parser_records_one_based_page_numbers() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)

    sections = get_parser("application/pdf").parse(output.getvalue())

    assert len(sections) == 1
    assert sections[0].page_number == 1

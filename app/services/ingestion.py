import logging
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.metrics import INGESTION_FAILURES, INGESTIONS
from app.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.ingestion import (
    DocumentParsingError,
    RecursiveTextChunker,
    TextChunk,
    get_parser,
)
from app.models.document import Document, DocumentChunk
from app.models.workspace import Workspace
from app.storage import ObjectStorage, ObjectStorageError
from app.vector import (
    VectorPoint,
    VectorStore,
    VectorStoreConfigurationError,
    VectorStoreError,
)

logger = logging.getLogger(__name__)
MAX_FAILURE_REASON_LENGTH = 2000


@dataclass(frozen=True, slots=True)
class IngestionDocument:
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    storage_key: str
    content_type: str


async def ingest_document(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    document_id: UUID,
    *,
    chunk_size: int,
    chunk_overlap: int,
    embedding_dimensions: int,
) -> None:
    document = await _mark_processing(session_factory, document_id)
    if document is None:
        return
    INGESTIONS.labels("started").inc()

    vectors_written = False
    try:
        await vector_store.ensure_collection(embedding_dimensions)
        content = await storage.download_file(document.storage_key)
        sections = get_parser(document.content_type).parse(content)
        chunks = RecursiveTextChunker(chunk_size, chunk_overlap).chunk_sections(
            sections
        )
        if not chunks:
            raise DocumentParsingError(
                "The document did not contain any extractable text"
            )
        embeddings = await embedding_provider.embed_documents(
            [chunk.text for chunk in chunks]
        )
        if len(embeddings) != len(chunks):
            raise EmbeddingProviderError(
                "The embedding provider returned an unexpected vector count"
            )
        points = [
            _build_vector_point(document, index, chunk, embedding)
            for index, (chunk, embedding) in enumerate(
                zip(chunks, embeddings, strict=True)
            )
        ]
        await vector_store.replace_document_vectors(document.id, points)
        vectors_written = True
        await _store_chunks(session_factory, document_id, chunks)
    except DocumentParsingError as exc:
        await _cleanup_vectors(vector_store, document_id)
        await _mark_failed(session_factory, document_id, str(exc))
    except EmbeddingProviderError:
        await _cleanup_vectors(vector_store, document_id)
        await _mark_failed(
            session_factory,
            document_id,
            "Embedding generation failed",
        )
    except VectorStoreConfigurationError:
        await _mark_failed(
            session_factory,
            document_id,
            "Vector index configuration is incompatible",
        )
    except VectorStoreError as exc:
        await _cleanup_vectors(vector_store, document_id)
        await _mark_failed(
            session_factory,
            document_id,
            "Document vectors could not be indexed",
        )
        raise RuntimeError("Vector indexing failed") from exc
    except ObjectStorageError as exc:
        await _mark_failed(
            session_factory,
            document_id,
            "The stored document could not be read",
        )
        raise RuntimeError("Object storage download failed") from exc
    except Exception:
        logger.exception(
            "Unexpected document ingestion failure",
            extra={"document_id": str(document_id)},
        )
        await _mark_failed(
            session_factory,
            document_id,
            "Document ingestion failed unexpectedly",
        )
        if vectors_written:
            await _cleanup_vectors(vector_store, document_id)
        raise


async def _mark_processing(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: UUID,
) -> IngestionDocument | None:
    async with session_factory() as session, session.begin():
        row = (
            await session.execute(
                select(Document, Workspace.organization_id)
                .join(Workspace, Workspace.id == Document.workspace_id)
                .where(Document.id == document_id)
                .with_for_update(of=Document)
            )
        ).one_or_none()
        if row is None:
            logger.warning(
                "Skipping ingestion for missing document",
                extra={"document_id": str(document_id)},
            )
            return None
        document, organization_id = row
        if document.status == "ready":
            return None
        document.status = "processing"
        document.failure_reason = None
        return IngestionDocument(
            id=document.id,
            organization_id=organization_id,
            workspace_id=document.workspace_id,
            storage_key=document.storage_key,
            content_type=document.content_type,
        )


def _build_vector_point(
    document: IngestionDocument,
    chunk_index: int,
    chunk: TextChunk,
    embedding: list[float],
) -> VectorPoint:
    chunk_id = uuid5(document.id, f"chunk:{chunk_index}")
    payload: dict[str, str | int] = {
        "organization_id": str(document.organization_id),
        "workspace_id": str(document.workspace_id),
        "document_id": str(document.id),
        "chunk_id": str(chunk_id),
        "chunk_index": chunk_index,
    }
    if chunk.page_number is not None:
        payload["page_number"] = chunk.page_number
    return VectorPoint(id=chunk_id, vector=embedding, payload=payload)


async def _cleanup_vectors(
    vector_store: VectorStore,
    document_id: UUID,
) -> None:
    try:
        await vector_store.delete_document_vectors(document_id)
    except VectorStoreError:
        logger.exception(
            "Failed to clean up document vectors",
            extra={"document_id": str(document_id)},
        )


async def _store_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: UUID,
    chunks: list[TextChunk],
) -> None:
    stored = False
    async with session_factory() as session, session.begin():
        document = await session.scalar(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
        )
        if document is None or document.status == "ready":
            return
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        session.add_all(
            DocumentChunk(
                document_id=document_id,
                chunk_index=index,
                text=chunk.text,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
            )
            for index, chunk in enumerate(chunks)
        )
        document.status = "ready"
        document.failure_reason = None
        stored = True
    if stored:
        INGESTIONS.labels("ready").inc()


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: UUID,
    reason: str,
) -> None:
    failed = False
    async with session_factory() as session, session.begin():
        document = await session.scalar(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
        )
        if document is None or document.status == "ready":
            return
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        document.status = "failed"
        document.failure_reason = reason[:MAX_FAILURE_REASON_LENGTH]
        failed = True
    if failed:
        INGESTIONS.labels("failed").inc()
        INGESTION_FAILURES.inc()

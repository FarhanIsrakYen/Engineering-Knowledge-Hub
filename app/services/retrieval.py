from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.models.document import Document, DocumentChunk
from app.models.workspace import Workspace
from app.vector import VectorStore, VectorStoreError


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    page_number: int | None
    section_title: str | None
    score: float


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store

    async def search(
        self,
        workspace_id: UUID,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            raise ApplicationError(
                "Search query cannot be empty",
                code="invalid_search_query",
                status_code=422,
            )
        if limit < 1 or limit > 50:
            raise ApplicationError(
                "Search limit must be between 1 and 50",
                code="invalid_search_limit",
                status_code=422,
            )

        organization_id = await self._session.scalar(
            select(Workspace.organization_id).where(Workspace.id == workspace_id)
        )
        if organization_id is None:
            return []

        try:
            query_vector = await self._embedding_provider.embed_query(query)
            vector_results = await self._vector_store.search_workspace(
                organization_id,
                workspace_id,
                query_vector,
                limit,
            )
        except (EmbeddingProviderError, VectorStoreError) as exc:
            raise ApplicationError(
                "Retrieval service is unavailable",
                code="retrieval_unavailable",
                status_code=503,
            ) from exc

        if not vector_results:
            return []

        identities = [
            (result.document_id, result.chunk_index)
            for result in vector_results
        ]
        chunks = await self._session.scalars(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.workspace_id == workspace_id,
                Document.status == "ready",
                tuple_(
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_index,
                ).in_(identities),
            )
        )
        chunks_by_identity = {
            (chunk.document_id, chunk.chunk_index): chunk for chunk in chunks
        }
        results: list[RetrievedChunk] = []
        for result in vector_results:
            chunk = chunks_by_identity.get(
                (result.document_id, result.chunk_index)
            )
            if chunk is None:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    chunk_index=result.chunk_index,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    score=result.score,
                )
            )
        return results

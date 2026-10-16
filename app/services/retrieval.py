import asyncio
from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy import desc, func, literal_column, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.models.document import Document, DocumentChunk
from app.models.workspace import Workspace
from app.vector import VectorSearchResult, VectorStore, VectorStoreError

logger = logging.getLogger(__name__)

RetrievalMode = Literal["vector", "lexical", "hybrid"]
ChunkIdentity = tuple[UUID, int]
RRF_RANK_CONSTANT = 60


@dataclass(frozen=True, slots=True)
class LexicalSearchResult:
    document_id: UUID
    chunk_index: int
    score: float


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    document_id: UUID
    chunk_index: int
    score: float
    vector_score: float | None
    matched_lexically: bool


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    chunk_index: int
    text: str
    page_number: int | None
    section_title: str | None
    score: float
    vector_score: float | None
    matched_lexically: bool


class RetrievalService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        mode: RetrievalMode = "hybrid",
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._mode = mode

    async def search(
        self,
        workspace_id: UUID,
        query: str,
        limit: int,
        *,
        mode: RetrievalMode | None = None,
    ) -> list[RetrievedChunk]:
        started_at = perf_counter()
        selected_mode = mode or self._mode
        self._validate_search(query, limit, selected_mode)

        organization_id = await self._session.scalar(
            select(Workspace.organization_id).where(Workspace.id == workspace_id)
        )
        if organization_id is None:
            self._log_diagnostics(selected_mode, 0, started_at)
            return []

        vector_results: list[VectorSearchResult] = []
        lexical_results: list[LexicalSearchResult] = []
        if selected_mode == "vector":
            vector_results = await self._vector_search(
                organization_id,
                workspace_id,
                query,
                limit,
            )
        elif selected_mode == "lexical":
            lexical_results = await self._lexical_search(
                workspace_id,
                query,
                limit,
            )
        else:
            vector_results, lexical_results = await asyncio.gather(
                self._vector_search(
                    organization_id,
                    workspace_id,
                    query,
                    limit,
                ),
                self._lexical_search(workspace_id, query, limit),
            )

        candidates = self._rank_candidates(
            selected_mode,
            vector_results,
            lexical_results,
        )
        candidate_count = len(candidates)
        results = await self._hydrate_chunks(
            workspace_id,
            candidates[:limit],
        )
        self._log_diagnostics(selected_mode, candidate_count, started_at)
        return results

    @staticmethod
    def _validate_search(query: str, limit: int, mode: str) -> None:
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
        if mode not in {"vector", "lexical", "hybrid"}:
            raise ApplicationError(
                "Retrieval mode is invalid",
                code="invalid_retrieval_mode",
                status_code=500,
            )

    async def _vector_search(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        query: str,
        limit: int,
    ) -> list[VectorSearchResult]:
        try:
            query_vector = await self._embedding_provider.embed_query(query)
            return await self._vector_store.search_workspace(
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

    async def _lexical_search(
        self,
        workspace_id: UUID,
        query: str,
        limit: int,
    ) -> list[LexicalSearchResult]:
        search_config = literal_column("'english'")
        search_vector = func.to_tsvector(search_config, DocumentChunk.text)
        search_query = func.websearch_to_tsquery(search_config, query)
        rank = func.ts_rank_cd(search_vector, search_query).label("rank")
        try:
            rows = await self._session.execute(
                select(
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_index,
                    rank,
                )
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    Document.workspace_id == workspace_id,
                    Document.status == "ready",
                    search_vector.op("@@")(search_query),
                )
                .order_by(
                    desc(rank),
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_index,
                )
                .limit(limit)
            )
        except SQLAlchemyError as exc:
            raise ApplicationError(
                "Retrieval service is unavailable",
                code="retrieval_unavailable",
                status_code=503,
            ) from exc
        return [
            LexicalSearchResult(
                document_id=document_id,
                chunk_index=chunk_index,
                score=float(score),
            )
            for document_id, chunk_index, score in rows
        ]

    @staticmethod
    def _rank_candidates(
        mode: RetrievalMode,
        vector_results: list[VectorSearchResult],
        lexical_results: list[LexicalSearchResult],
    ) -> list[RankedCandidate]:
        vector_scores = {
            (result.document_id, result.chunk_index): result.score
            for result in vector_results
        }
        lexical_scores = {
            (result.document_id, result.chunk_index): result.score
            for result in lexical_results
        }

        if mode == "vector":
            return [
                RankedCandidate(
                    result.document_id,
                    result.chunk_index,
                    result.score,
                    result.score,
                    False,
                )
                for result in vector_results
            ]
        if mode == "lexical":
            return [
                RankedCandidate(
                    result.document_id,
                    result.chunk_index,
                    result.score,
                    None,
                    True,
                )
                for result in lexical_results
            ]

        fused_scores: dict[ChunkIdentity, float] = {}
        for ranking in (vector_results, lexical_results):
            for rank, result in enumerate(ranking, start=1):
                identity = (result.document_id, result.chunk_index)
                fused_scores[identity] = fused_scores.get(identity, 0.0) + (
                    1 / (RRF_RANK_CONSTANT + rank)
                )
        ordered = sorted(
            fused_scores,
            key=lambda identity: (
                -fused_scores[identity],
                str(identity[0]),
                identity[1],
            ),
        )
        return [
            RankedCandidate(
                document_id=document_id,
                chunk_index=chunk_index,
                score=fused_scores[(document_id, chunk_index)],
                vector_score=vector_scores.get((document_id, chunk_index)),
                matched_lexically=(document_id, chunk_index) in lexical_scores,
            )
            for document_id, chunk_index in ordered
        ]

    async def _hydrate_chunks(
        self,
        workspace_id: UUID,
        candidates: list[RankedCandidate],
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        identities = [
            (candidate.document_id, candidate.chunk_index)
            for candidate in candidates
        ]
        rows = await self._session.execute(
            select(DocumentChunk, Document.original_filename)
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
            (chunk.document_id, chunk.chunk_index): (chunk, filename)
            for chunk, filename in rows
        }
        results: list[RetrievedChunk] = []
        for candidate in candidates:
            chunk_record = chunks_by_identity.get(
                (candidate.document_id, candidate.chunk_index)
            )
            if chunk_record is None:
                continue
            chunk, filename = chunk_record
            results.append(
                RetrievedChunk(
                    chunk_id=uuid5(
                        candidate.document_id,
                        f"chunk:{candidate.chunk_index}",
                    ),
                    document_id=candidate.document_id,
                    filename=filename,
                    chunk_index=candidate.chunk_index,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    score=candidate.score,
                    vector_score=candidate.vector_score,
                    matched_lexically=candidate.matched_lexically,
                )
            )
        return results

    @staticmethod
    def _log_diagnostics(
        mode: RetrievalMode,
        candidate_count: int,
        started_at: float,
    ) -> None:
        logger.info(
            "Retrieval completed",
            extra={
                "retrieval_mode": mode,
                "candidate_count": candidate_count,
                "retrieval_latency_ms": round(
                    (perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )

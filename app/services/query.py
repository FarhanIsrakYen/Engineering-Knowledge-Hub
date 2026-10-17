import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ApplicationError
from app.core.metrics import GENERATION_DURATION, RAG_QUERY_DURATION
from app.embeddings import EmbeddingProvider
from app.llm import LLMProvider, LLMProviderError
from app.rag import (
    SYSTEM_PROMPT,
    ConversationTurn,
    QueryRewriter,
    QueryRewriterError,
    Reranker,
    RerankerError,
    build_query_prompt,
)
from app.services.retrieval import RetrievalService, RetrievedChunk
from app.vector import VectorStore

INSUFFICIENT_CONTEXT_ANSWER = (
    "The available workspace context is insufficient to answer this question."
)

logger = logging.getLogger(__name__)


def build_query_service(
    session: AsyncSession,
    embedding_provider: EmbeddingProvider,
    vector_store: VectorStore,
    llm_provider: LLMProvider,
    query_rewriter: QueryRewriter,
    reranker: Reranker,
    settings: Settings,
) -> "QueryService":
    return QueryService(
        RetrievalService(
            session,
            embedding_provider,
            vector_store,
            settings.retrieval_mode,
        ),
        llm_provider,
        settings.rag_min_similarity,
        query_rewriter,
        reranker,
        rewriting_enabled=settings.query_rewriting_enabled,
        reranking_enabled=settings.reranking_enabled,
        candidate_count=settings.rag_candidate_count,
    )


class ChunkRetriever(Protocol):
    async def search(
        self,
        workspace_id: UUID,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]: ...


@dataclass(frozen=True, slots=True)
class QuerySource:
    document_id: UUID
    filename: str
    page: int | None
    chunk_id: UUID
    score: float


@dataclass(frozen=True, slots=True)
class QueryResult:
    answer: str
    sources: list[QuerySource]
    timings: dict[str, float]
    context_texts: list[str]


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    question: str
    retrieval_query: str
    context_chunks: list[RetrievedChunk]
    timings: dict[str, float]
    candidate_count: int
    started_at: float


class QueryService:
    def __init__(
        self,
        retrieval_service: ChunkRetriever,
        llm_provider: LLMProvider,
        minimum_similarity: float,
        query_rewriter: QueryRewriter,
        reranker: Reranker,
        *,
        rewriting_enabled: bool,
        reranking_enabled: bool,
        candidate_count: int,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._llm_provider = llm_provider
        self._minimum_similarity = minimum_similarity
        self._query_rewriter = query_rewriter
        self._reranker = reranker
        self._rewriting_enabled = rewriting_enabled
        self._reranking_enabled = reranking_enabled
        self._candidate_count = candidate_count

    async def query(
        self,
        workspace_id: UUID,
        question: str,
        top_k: int,
    ) -> QueryResult:
        prepared = await self.prepare(workspace_id, question, top_k)
        if not prepared.context_chunks:
            self._log_diagnostics(prepared)
            return QueryResult(
                answer=INSUFFICIENT_CONTEXT_ANSWER,
                sources=[],
                timings=prepared.timings,
                context_texts=[],
            )

        stage_started_at = perf_counter()
        try:
            try:
                answer = await self._llm_provider.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=self._build_prompt(prepared),
                )
            except LLMProviderError as exc:
                raise ApplicationError(
                    "The answer generation service is unavailable",
                    code="llm_provider_unavailable",
                    status_code=503,
                ) from exc
            return QueryResult(
                answer=answer,
                sources=self.sources(prepared),
                timings=prepared.timings,
                context_texts=[
                    chunk.text for chunk in prepared.context_chunks
                ],
            )
        finally:
            prepared.timings["generation_latency_ms"] = self._elapsed_ms(
                stage_started_at
            )
            self._log_diagnostics(prepared)

    async def prepare(
        self,
        workspace_id: UUID,
        question: str,
        top_k: int,
        history: list[ConversationTurn] | None = None,
    ) -> PreparedQuery:
        if top_k > self._candidate_count:
            raise ApplicationError(
                "top_k cannot exceed the configured candidate count",
                code="invalid_query_top_k",
                status_code=422,
            )

        started_at = perf_counter()
        timings = {
            "query_rewrite_latency_ms": 0.0,
            "query_retrieval_latency_ms": 0.0,
            "rerank_latency_ms": 0.0,
            "generation_latency_ms": 0.0,
        }
        retrieved_count = 0
        try:
            stage_started_at = perf_counter()
            retrieval_query = question.strip()
            try:
                if self._rewriting_enabled or history:
                    try:
                        retrieval_query = await self._query_rewriter.rewrite(
                            question,
                            history,
                        )
                    except QueryRewriterError as exc:
                        raise ApplicationError(
                            "Query rewriting is unavailable",
                            code="query_rewriter_unavailable",
                            status_code=503,
                        ) from exc
            finally:
                timings["query_rewrite_latency_ms"] = self._elapsed_ms(
                    stage_started_at
                )

            stage_started_at = perf_counter()
            try:
                chunks = await self._retrieval_service.search(
                    workspace_id,
                    retrieval_query,
                    self._candidate_count,
                )
            finally:
                timings["query_retrieval_latency_ms"] = self._elapsed_ms(
                    stage_started_at
                )
            retrieved_count = len(chunks)
            relevant_chunks = [
                chunk
                for chunk in chunks
                if chunk.matched_lexically
                or (
                    chunk.vector_score is not None
                    and chunk.vector_score >= self._minimum_similarity
                )
            ]

            stage_started_at = perf_counter()
            try:
                if self._reranking_enabled and relevant_chunks:
                    relevant_chunks = await self._rerank(
                        retrieval_query,
                        relevant_chunks,
                    )
            finally:
                timings["rerank_latency_ms"] = self._elapsed_ms(
                    stage_started_at
                )

            return PreparedQuery(
                question=question,
                retrieval_query=retrieval_query,
                context_chunks=relevant_chunks[:top_k],
                timings=timings,
                candidate_count=retrieved_count,
                started_at=started_at,
            )
        except Exception:
            total_latency_ms = self._elapsed_ms(started_at)
            RAG_QUERY_DURATION.observe(total_latency_ms / 1000)
            logger.info(
                "RAG query preparation failed",
                extra={
                    **timings,
                    "query_total_latency_ms": total_latency_ms,
                    "candidate_count": retrieved_count,
                    "final_context_count": 0,
                },
            )
            raise

    async def stream(self, prepared: PreparedQuery) -> AsyncGenerator[str, None]:
        stage_started_at = perf_counter()
        try:
            if not prepared.context_chunks:
                yield INSUFFICIENT_CONTEXT_ANSWER
                return
            try:
                async for delta in self._llm_provider.stream(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=self._build_prompt(prepared),
                ):
                    yield delta
            except LLMProviderError as exc:
                raise ApplicationError(
                    "The answer generation service is unavailable",
                    code="llm_provider_unavailable",
                    status_code=503,
                ) from exc
        finally:
            prepared.timings["generation_latency_ms"] = self._elapsed_ms(
                stage_started_at
            )
            self._log_diagnostics(prepared)

    @staticmethod
    def sources(prepared: PreparedQuery) -> list[QuerySource]:
        return [
            QuerySource(
                document_id=chunk.document_id,
                filename=chunk.filename,
                page=chunk.page_number,
                chunk_id=chunk.chunk_id,
                score=chunk.score,
            )
            for chunk in prepared.context_chunks
        ]

    async def _rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        try:
            scores = await self._reranker.score(
                query,
                [chunk.text for chunk in chunks],
            )
        except RerankerError as exc:
            raise ApplicationError(
                "Reranking is unavailable",
                code="reranker_unavailable",
                status_code=503,
            ) from exc
        if len(scores) != len(chunks):
            raise ApplicationError(
                "Reranking is unavailable",
                code="reranker_unavailable",
                status_code=503,
            )
        reranked = [
            replace(chunk, score=score)
            for chunk, score in zip(chunks, scores, strict=True)
        ]
        return sorted(reranked, key=lambda chunk: chunk.score, reverse=True)

    @staticmethod
    def _build_prompt(prepared: PreparedQuery) -> str:
        return build_query_prompt(
            prepared.question,
            prepared.context_chunks,
            prepared.retrieval_query,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 2)

    def _log_diagnostics(self, prepared: PreparedQuery) -> None:
        total_latency_ms = self._elapsed_ms(prepared.started_at)
        prepared.timings["total_latency_ms"] = total_latency_ms
        RAG_QUERY_DURATION.observe(total_latency_ms / 1000)
        if prepared.timings["generation_latency_ms"] > 0:
            GENERATION_DURATION.observe(
                prepared.timings["generation_latency_ms"] / 1000
            )
        logger.info(
            "RAG query completed",
            extra={
                **prepared.timings,
                "query_total_latency_ms": total_latency_ms,
                "candidate_count": prepared.candidate_count,
                "final_context_count": len(prepared.context_chunks),
            },
        )

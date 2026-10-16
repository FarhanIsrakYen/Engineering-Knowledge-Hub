from dataclasses import dataclass, replace
import logging
from time import perf_counter
from typing import Protocol
from uuid import UUID

from app.core.exceptions import ApplicationError
from app.llm import LLMProvider, LLMProviderError
from app.rag import (
    QueryRewriter,
    QueryRewriterError,
    Reranker,
    RerankerError,
    SYSTEM_PROMPT,
    build_query_prompt,
)
from app.services.retrieval import RetrievedChunk

INSUFFICIENT_CONTEXT_ANSWER = (
    "The available workspace context is insufficient to answer this question."
)

logger = logging.getLogger(__name__)


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
        final_context_count = 0
        try:
            stage_started_at = perf_counter()
            retrieval_query = question.strip()
            try:
                if self._rewriting_enabled:
                    try:
                        retrieval_query = await self._query_rewriter.rewrite(
                            question
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
            if not relevant_chunks:
                return QueryResult(
                    answer=INSUFFICIENT_CONTEXT_ANSWER,
                    sources=[],
                )

            stage_started_at = perf_counter()
            try:
                if self._reranking_enabled:
                    relevant_chunks = await self._rerank(
                        retrieval_query,
                        relevant_chunks,
                    )
            finally:
                timings["rerank_latency_ms"] = self._elapsed_ms(
                    stage_started_at
                )
            context_chunks = relevant_chunks[:top_k]
            final_context_count = len(context_chunks)

            stage_started_at = perf_counter()
            try:
                answer = await self._llm_provider.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=build_query_prompt(question, context_chunks),
                )
            except LLMProviderError as exc:
                raise ApplicationError(
                    "The answer generation service is unavailable",
                    code="llm_provider_unavailable",
                    status_code=503,
                ) from exc
            finally:
                timings["generation_latency_ms"] = self._elapsed_ms(
                    stage_started_at
                )

            return QueryResult(
                answer=answer,
                sources=[
                    QuerySource(
                        document_id=chunk.document_id,
                        filename=chunk.filename,
                        page=chunk.page_number,
                        chunk_id=chunk.chunk_id,
                        score=chunk.score,
                    )
                    for chunk in context_chunks
                ],
            )
        finally:
            logger.info(
                "RAG query completed",
                extra={
                    **timings,
                    "query_total_latency_ms": self._elapsed_ms(started_at),
                    "candidate_count": retrieved_count,
                    "final_context_count": final_context_count,
                },
            )

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
    def _elapsed_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 2)

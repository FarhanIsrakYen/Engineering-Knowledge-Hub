import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_database_engine, create_session_factory
from app.embeddings import CachedQueryEmbeddingProvider, FastEmbedEmbeddingProvider
from app.evaluation import LLMAnswerEvaluator
from app.llm import OpenAILLMProvider
from app.models.workspace import Workspace
from app.rag import FastEmbedReranker, LLMQueryRewriter
from app.schemas.evaluation import EvaluationDatasetItem
from app.services.evaluation import EvaluationService
from app.services.query import build_query_service
from app.vector import QdrantVectorStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an Engineering Knowledge Hub RAG evaluation",
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--llm-judge", action="store_true")
    arguments = parser.parse_args()
    try:
        dataset = TypeAdapter(list[EvaluationDatasetItem]).validate_json(
            arguments.dataset.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        parser.error(f"invalid evaluation dataset: {exc}")
    asyncio.run(
        _run(
            arguments.workspace_id,
            dataset,
            arguments.top_k,
            arguments.llm_judge,
        )
    )


async def _run(
    workspace_id: UUID,
    dataset: list[EvaluationDatasetItem],
    top_k: int | None,
    use_llm_judge: bool,
) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    selected_top_k = top_k or settings.rag_default_top_k
    if selected_top_k > settings.rag_candidate_count:
        raise SystemExit("top-k cannot exceed EKH_RAG_CANDIDATE_COUNT")

    engine = create_database_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    embedding_provider = CachedQueryEmbeddingProvider(
        FastEmbedEmbeddingProvider(
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.embedding_cache_dir,
        ),
        redis,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.query_embedding_cache_ttl_seconds,
    )
    vector_store = QdrantVectorStore(
        url=settings.qdrant_url,
        api_key=(
            settings.qdrant_api_key.get_secret_value()
            if settings.qdrant_api_key is not None
            else None
        ),
        collection=settings.qdrant_collection,
        embedding_model=settings.embedding_model,
    )
    llm_provider = OpenAILLMProvider(
        api_key=(
            settings.llm_api_key.get_secret_value()
            if settings.llm_api_key is not None
            else None
        ),
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    query_rewriter = LLMQueryRewriter(llm_provider)
    reranker = FastEmbedReranker(
        model_name=settings.reranker_model,
        cache_dir=settings.reranker_cache_dir or settings.embedding_cache_dir,
    )
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            if await session.get(Workspace, workspace_id) is None:
                raise SystemExit(f"workspace {workspace_id} does not exist")
            query_service = build_query_service(
                session,
                embedding_provider,
                vector_store,
                llm_provider,
                query_rewriter,
                reranker,
                settings,
            )
            run = await EvaluationService(
                session,
                query_service,
                LLMAnswerEvaluator(llm_provider),
            ).run(
                workspace_id,
                None,
                dataset,
                selected_top_k,
                use_llm_judge=use_llm_judge,
            )
            print(
                json.dumps(
                    {
                        "run_id": str(run.id),
                        "status": run.status,
                        "metrics": run.metrics,
                        "failure_reason": run.failure_reason,
                    },
                    indent=2,
                )
            )
    finally:
        try:
            await query_rewriter.close()
        finally:
            try:
                await reranker.close()
            finally:
                try:
                    await llm_provider.close()
                finally:
                    try:
                        await embedding_provider.close()
                    finally:
                        try:
                            await vector_store.close()
                        finally:
                            try:
                                await redis.aclose()
                            finally:
                                await engine.dispose()

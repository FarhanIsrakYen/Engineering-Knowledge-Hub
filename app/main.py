import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestObservabilityMiddleware
from app.db.session import create_database_engine, create_session_factory
from app.embeddings import (
    CachedQueryEmbeddingProvider,
    EmbeddingProvider,
    FastEmbedEmbeddingProvider,
)
from app.evaluation import AnswerEvaluator, LLMAnswerEvaluator
from app.ingestion.queue import CeleryIngestionQueue, IngestionQueue
from app.llm import LLMProvider, OpenAILLMProvider
from app.rag import (
    FastEmbedReranker,
    LLMQueryRewriter,
    QueryRewriter,
    Reranker,
)
from app.services.rate_limit import RateLimiter, RedisRateLimiter
from app.storage import ObjectStorage, S3ObjectStorage
from app.vector import QdrantVectorStore, VectorStore

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    object_storage: ObjectStorage | None = None,
    ingestion_queue: IngestionQueue | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: VectorStore | None = None,
    llm_provider: LLMProvider | None = None,
    query_rewriter: QueryRewriter | None = None,
    reranker: Reranker | None = None,
    redis_client: Redis | None = None,
    rate_limiter: RateLimiter | None = None,
    answer_evaluator: AnswerEvaluator | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(app_settings.database_url)
        storage = object_storage or S3ObjectStorage(
            endpoint_url=app_settings.object_storage_endpoint_url,
            access_key=app_settings.object_storage_access_key,
            secret_key=app_settings.object_storage_secret_key.get_secret_value(),
            bucket=app_settings.object_storage_bucket,
            region=app_settings.object_storage_region,
        )
        queue = ingestion_queue or CeleryIngestionQueue(app_settings.redis_url)
        redis = redis_client or Redis.from_url(
            app_settings.redis_url,
            decode_responses=True,
        )
        embedder: EmbeddingProvider
        if embedding_provider is None:
            embedder = CachedQueryEmbeddingProvider(
                FastEmbedEmbeddingProvider(
                    app_settings.embedding_model,
                    app_settings.embedding_dimensions,
                    app_settings.embedding_cache_dir,
                ),
                redis,
                app_settings.embedding_model,
                app_settings.embedding_dimensions,
                app_settings.query_embedding_cache_ttl_seconds,
            )
        else:
            embedder = embedding_provider
        vectors = vector_store or QdrantVectorStore(
            url=app_settings.qdrant_url,
            api_key=(
                app_settings.qdrant_api_key.get_secret_value()
                if app_settings.qdrant_api_key is not None
                else None
            ),
            collection=app_settings.qdrant_collection,
            embedding_model=app_settings.embedding_model,
        )
        llm = llm_provider or OpenAILLMProvider(
            api_key=(
                app_settings.llm_api_key.get_secret_value()
                if app_settings.llm_api_key is not None
                else None
            ),
            model=app_settings.llm_model,
            base_url=app_settings.llm_base_url,
            timeout_seconds=app_settings.llm_timeout_seconds,
            max_output_tokens=app_settings.llm_max_output_tokens,
        )
        rewriter = query_rewriter or LLMQueryRewriter(llm)
        ranker = reranker or FastEmbedReranker(
            model_name=app_settings.reranker_model,
            cache_dir=(
                app_settings.reranker_cache_dir
                or app_settings.embedding_cache_dir
            ),
        )
        application.state.db_engine = engine
        application.state.db_session_factory = create_session_factory(engine)
        application.state.object_storage = storage
        application.state.ingestion_queue = queue
        application.state.embedding_provider = embedder
        application.state.vector_store = vectors
        application.state.llm_provider = llm
        application.state.query_rewriter = rewriter
        application.state.reranker = ranker
        application.state.redis = redis
        application.state.rate_limiter = rate_limiter or RedisRateLimiter(redis)
        application.state.answer_evaluator = (
            answer_evaluator or LLMAnswerEvaluator(llm)
        )
        try:
            if app_settings.object_storage_auto_create_bucket:
                await storage.ensure_bucket()
            if app_settings.qdrant_auto_initialize:
                await vectors.ensure_collection(
                    app_settings.embedding_dimensions
                )
            logger.info(
                "Application started",
                extra={"environment": app_settings.environment},
            )
            yield
        finally:
            try:
                await rewriter.close()
            finally:
                try:
                    await ranker.close()
                finally:
                    try:
                        await llm.close()
                    finally:
                        try:
                            await embedder.close()
                        finally:
                            try:
                                await vectors.close()
                            finally:
                                try:
                                    await queue.close()
                                finally:
                                    try:
                                        await storage.close()
                                    finally:
                                        try:
                                            await redis.aclose()
                                        finally:
                                            await engine.dispose()
            logger.info("Application stopped")

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.add_middleware(RequestObservabilityMiddleware)
    application.include_router(health_router, include_in_schema=False)
    application.include_router(metrics_router)
    application.include_router(api_router, prefix="/api/v1")
    register_exception_handlers(application)
    return application


app = create_app()

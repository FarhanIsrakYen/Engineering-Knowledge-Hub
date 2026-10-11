import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.embeddings import FastEmbedEmbeddingProvider
from app.services.ingestion import ingest_document
from app.storage import S3ObjectStorage
from app.vector import QdrantVectorStore
from app.worker.celery_app import celery_app


async def _ingest_document(document_id: UUID) -> None:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
    )
    embedding_provider = FastEmbedEmbeddingProvider(
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_cache_dir,
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
    try:
        await ingest_document(
            create_session_factory(engine),
            storage,
            embedding_provider,
            vector_store,
            document_id,
            chunk_size=settings.document_chunk_size,
            chunk_overlap=settings.document_chunk_overlap,
            embedding_dimensions=settings.embedding_dimensions,
        )
    finally:
        try:
            await embedding_provider.close()
        finally:
            try:
                await vector_store.close()
            finally:
                try:
                    await storage.close()
                finally:
                    await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.worker.tasks.ingest_document",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    acks_late=True,
)
def ingest_document_task(self: object, document_id: str) -> None:
    del self
    asyncio.run(_ingest_document(UUID(document_id)))

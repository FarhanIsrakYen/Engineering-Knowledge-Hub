from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.ingestion.queue import IngestionQueue
from app.storage import ObjectStorage, ObjectStorageError
from app.vector import VectorStore


async def verify_database_connection(session: AsyncSession) -> None:
    try:
        result = await session.execute(text("SELECT 1"))
        if result.scalar_one() != 1:
            raise ApplicationError(
                "Database readiness check returned an unexpected result",
                code="database_unavailable",
                status_code=503,
            )
    except (OSError, SQLAlchemyError) as exc:
        raise ApplicationError(
            "Database is unavailable",
            code="database_unavailable",
            status_code=503,
        ) from exc


async def verify_object_storage(storage: ObjectStorage) -> None:
    try:
        available = await storage.is_available()
    except ObjectStorageError as exc:
        raise ApplicationError(
            "Object storage is unavailable",
            code="object_storage_unavailable",
            status_code=503,
        ) from exc
    if not available:
        raise ApplicationError(
            "Object storage is unavailable",
            code="object_storage_unavailable",
            status_code=503,
        )


async def verify_ingestion_queue(queue: IngestionQueue) -> None:
    if not await queue.is_available():
        raise ApplicationError(
            "Ingestion queue is unavailable",
            code="ingestion_queue_unavailable",
            status_code=503,
        )


async def verify_vector_store(vector_store: VectorStore) -> None:
    if not await vector_store.is_available():
        raise ApplicationError(
            "Vector store is unavailable",
            code="vector_store_unavailable",
            status_code=503,
        )


async def verify_redis(redis: Redis) -> None:
    try:
        if not await redis.ping():
            raise ApplicationError(
                "Redis is unavailable",
                code="redis_unavailable",
                status_code=503,
            )
    except RedisError as exc:
        raise ApplicationError(
            "Redis is unavailable",
            code="redis_unavailable",
            status_code=503,
        ) from exc

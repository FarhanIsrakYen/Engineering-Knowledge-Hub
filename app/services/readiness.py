from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.storage import ObjectStorage, ObjectStorageError


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

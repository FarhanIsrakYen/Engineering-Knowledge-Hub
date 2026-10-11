import asyncio
from typing import Protocol
from uuid import UUID

from celery import Celery
from kombu.exceptions import OperationalError

INGEST_DOCUMENT_TASK = "app.worker.tasks.ingest_document"


class IngestionQueueError(Exception):
    pass


class IngestionQueue(Protocol):
    async def enqueue(self, document_id: UUID) -> None: ...

    async def is_available(self) -> bool: ...

    async def close(self) -> None: ...


class CeleryIngestionQueue:
    def __init__(self, redis_url: str) -> None:
        self._celery = Celery(broker=redis_url)

    async def enqueue(self, document_id: UUID) -> None:
        try:
            await asyncio.to_thread(
                self._celery.send_task,
                INGEST_DOCUMENT_TASK,
                args=[str(document_id)],
            )
        except (OSError, OperationalError) as exc:
            raise IngestionQueueError("Ingestion task could not be queued") from exc

    async def is_available(self) -> bool:
        def check_connection() -> None:
            with self._celery.connection_for_write() as connection:
                connection.ensure_connection(max_retries=0)

        try:
            await asyncio.to_thread(check_connection)
        except (OSError, OperationalError):
            return False
        return True

    async def close(self) -> None:
        await asyncio.to_thread(self._celery.close)

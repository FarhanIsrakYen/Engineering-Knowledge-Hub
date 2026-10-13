from uuid import UUID

from app.ingestion.queue import IngestionQueueError


class InMemoryIngestionQueue:
    def __init__(self, *, available: bool = True, fail_enqueue: bool = False) -> None:
        self.available = available
        self.fail_enqueue = fail_enqueue
        self.document_ids: list[UUID] = []
        self.closed = False

    async def enqueue(self, document_id: UUID) -> None:
        if self.fail_enqueue:
            raise IngestionQueueError("Queue unavailable")
        self.document_ids.append(document_id)

    async def is_available(self) -> bool:
        return self.available

    async def close(self) -> None:
        self.closed = True

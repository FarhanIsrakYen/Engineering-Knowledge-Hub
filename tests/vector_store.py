import math
from uuid import UUID

from app.vector import VectorPoint, VectorSearchResult, VectorStoreError


class InMemoryVectorStore:
    def __init__(
        self,
        *,
        available: bool = True,
        fail_writes: bool = False,
    ) -> None:
        self.available = available
        self.fail_writes = fail_writes
        self.dimensions: int | None = None
        self.points: dict[UUID, VectorPoint] = {}
        self.search_filters: list[tuple[UUID, UUID]] = []
        self.closed = False

    async def ensure_collection(self, dimensions: int) -> None:
        if not self.available:
            raise VectorStoreError("Vector store unavailable")
        self.dimensions = dimensions

    async def replace_document_vectors(
        self,
        document_id: UUID,
        points: list[VectorPoint],
    ) -> None:
        if self.fail_writes:
            raise VectorStoreError("Vector write failed")
        await self.delete_document_vectors(document_id)
        self.points.update({point.id: point for point in points})

    async def delete_document_vectors(self, document_id: UUID) -> None:
        self.points = {
            point_id: point
            for point_id, point in self.points.items()
            if point.payload["document_id"] != str(document_id)
        }

    async def search_workspace(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[VectorSearchResult]:
        self.search_filters.append((organization_id, workspace_id))
        matches = [
            point
            for point in self.points.values()
            if point.payload["organization_id"] == str(organization_id)
            and point.payload["workspace_id"] == str(workspace_id)
        ]
        scored = sorted(
            (
                (self._cosine(query_vector, point.vector), point)
                for point in matches
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        return [
            VectorSearchResult(
                chunk_id=UUID(str(point.payload["chunk_id"])),
                document_id=UUID(str(point.payload["document_id"])),
                chunk_index=int(point.payload["chunk_index"]),
                score=score,
            )
            for score, point in scored[:limit]
        ]

    async def is_available(self) -> bool:
        return self.available

    async def close(self) -> None:
        self.closed = True

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_size = math.sqrt(sum(value * value for value in left))
        right_size = math.sqrt(sum(value * value for value in right))
        return numerator / (left_size * right_size)

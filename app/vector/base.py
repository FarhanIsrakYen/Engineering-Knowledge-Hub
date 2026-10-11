from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class VectorStoreError(Exception):
    pass


class VectorStoreConfigurationError(VectorStoreError):
    pass


@dataclass(frozen=True, slots=True)
class VectorPoint:
    id: UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    score: float


class VectorStore(Protocol):
    async def ensure_collection(self, dimensions: int) -> None: ...

    async def replace_document_vectors(
        self,
        document_id: UUID,
        points: list[VectorPoint],
    ) -> None: ...

    async def delete_document_vectors(self, document_id: UUID) -> None: ...

    async def search_workspace(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[VectorSearchResult]: ...

    async def is_available(self) -> bool: ...

    async def close(self) -> None: ...

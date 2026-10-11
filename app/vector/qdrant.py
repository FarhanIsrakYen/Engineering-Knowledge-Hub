from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.vector.base import (
    VectorPoint,
    VectorSearchResult,
    VectorStoreConfigurationError,
    VectorStoreError,
)


class QdrantVectorStore:
    def __init__(
        self,
        *,
        url: str,
        api_key: str | None,
        collection: str,
        embedding_model: str,
    ) -> None:
        self._collection = collection
        self._embedding_model = embedding_model
        self._client = AsyncQdrantClient(url=url, api_key=api_key)

    async def ensure_collection(self, dimensions: int) -> None:
        try:
            if not await self._client.collection_exists(self._collection):
                try:
                    await self._client.create_collection(
                        collection_name=self._collection,
                        vectors_config=models.VectorParams(
                            size=dimensions,
                            distance=models.Distance.COSINE,
                        ),
                        metadata={
                            "embedding_model": self._embedding_model,
                            "embedding_dimensions": dimensions,
                        },
                    )
                except Exception:
                    if not await self._client.collection_exists(self._collection):
                        raise

            collection = await self._client.get_collection(self._collection)
            vectors = collection.config.params.vectors
            if not isinstance(vectors, models.VectorParams):
                raise VectorStoreConfigurationError(
                    "The Qdrant collection must contain one unnamed vector"
                )
            if (
                vectors.size != dimensions
                or vectors.distance != models.Distance.COSINE
            ):
                raise VectorStoreConfigurationError(
                    "The Qdrant collection configuration does not match "
                    "the application"
                )
            metadata = collection.config.metadata or {}
            if metadata.get("embedding_model") != self._embedding_model:
                raise VectorStoreConfigurationError(
                    "The Qdrant collection embedding model does not match "
                    "the application"
                )

            indexed_fields = collection.payload_schema
            for field_name in (
                "organization_id",
                "workspace_id",
                "document_id",
                "chunk_id",
            ):
                if field_name not in indexed_fields:
                    await self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name=field_name,
                        field_schema=models.PayloadSchemaType.UUID,
                        wait=True,
                    )
        except VectorStoreConfigurationError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                "The Qdrant collection could not be initialized"
            ) from exc

    async def replace_document_vectors(
        self,
        document_id: UUID,
        points: list[VectorPoint],
    ) -> None:
        try:
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._document_filter(document_id),
                wait=True,
            )
            await self._client.upsert(
                collection_name=self._collection,
                points=[
                    models.PointStruct(
                        id=point.id,
                        vector=point.vector,
                        payload=point.payload,
                    )
                    for point in points
                ],
                wait=True,
            )
        except Exception as exc:
            raise VectorStoreError(
                "Document vectors could not be stored"
            ) from exc

    async def delete_document_vectors(self, document_id: UUID) -> None:
        try:
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._document_filter(document_id),
                wait=True,
            )
        except Exception as exc:
            raise VectorStoreError(
                "Document vectors could not be deleted"
            ) from exc

    async def search_workspace(
        self,
        organization_id: UUID,
        workspace_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[VectorSearchResult]:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="organization_id",
                    match=models.MatchValue(value=str(organization_id)),
                ),
                models.FieldCondition(
                    key="workspace_id",
                    match=models.MatchValue(value=str(workspace_id)),
                ),
            ]
        )
        try:
            response = await self._client.query_points(
                collection_name=self._collection,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return [self._to_search_result(point) for point in response.points]
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError("Vector search failed") from exc

    async def is_available(self) -> bool:
        try:
            await self._client.get_collections()
        except Exception:
            return False
        return True

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _document_filter(document_id: UUID) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            ]
        )

    @staticmethod
    def _to_search_result(point: models.ScoredPoint) -> VectorSearchResult:
        payload = point.payload or {}
        try:
            return VectorSearchResult(
                chunk_id=UUID(str(payload["chunk_id"])),
                document_id=UUID(str(payload["document_id"])),
                chunk_index=int(payload["chunk_index"]),
                score=point.score,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VectorStoreError(
                "A vector search result contained invalid metadata"
            ) from exc

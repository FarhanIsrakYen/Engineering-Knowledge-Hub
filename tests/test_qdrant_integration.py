import asyncio
import os
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient

from app.vector import (
    QdrantVectorStore,
    VectorPoint,
    VectorStoreConfigurationError,
)


@pytest.mark.integration
def test_qdrant_initialization_indexing_and_tenant_filtering() -> None:
    if os.getenv("EKH_TEST_QDRANT") != "true":
        pytest.skip("EKH_TEST_QDRANT=true is required for the Qdrant test")

    qdrant_url = os.getenv("EKH_QDRANT_URL", "http://localhost:6333")
    collection = f"integration_test_{uuid4().hex}"

    async def exercise_qdrant() -> None:
        store = QdrantVectorStore(
            url=qdrant_url,
            api_key=None,
            collection=collection,
            embedding_model="test/embedding-model",
        )
        cleanup_client = AsyncQdrantClient(url=qdrant_url)
        try:
            await store.ensure_collection(3)
            await store.ensure_collection(3)
            with pytest.raises(VectorStoreConfigurationError):
                await store.ensure_collection(4)

            organization_id = uuid4()
            workspace_id = uuid4()
            document_id = uuid4()
            other_workspace_id = uuid4()
            other_document_id = uuid4()
            point_id = uuid4()
            other_point_id = uuid4()
            await store.replace_document_vectors(
                document_id,
                [
                    VectorPoint(
                        id=point_id,
                        vector=[1.0, 0.0, 0.0],
                        payload={
                            "organization_id": str(organization_id),
                            "workspace_id": str(workspace_id),
                            "document_id": str(document_id),
                            "chunk_id": str(point_id),
                            "chunk_index": 0,
                        },
                    )
                ],
            )
            await store.replace_document_vectors(
                other_document_id,
                [
                    VectorPoint(
                        id=other_point_id,
                        vector=[1.0, 0.0, 0.0],
                        payload={
                            "organization_id": str(organization_id),
                            "workspace_id": str(other_workspace_id),
                            "document_id": str(other_document_id),
                            "chunk_id": str(other_point_id),
                            "chunk_index": 0,
                        },
                    )
                ],
            )

            results = await store.search_workspace(
                organization_id,
                workspace_id,
                [1.0, 0.0, 0.0],
                10,
            )

            assert [result.document_id for result in results] == [document_id]
            collection_info = await cleanup_client.get_collection(collection)
            assert {
                "organization_id",
                "workspace_id",
                "document_id",
                "chunk_id",
            } <= collection_info.payload_schema.keys()
            assert collection_info.config.metadata == {
                "embedding_model": "test/embedding-model",
                "embedding_dimensions": 3,
            }
        finally:
            await store.close()
            if await cleanup_client.collection_exists(collection):
                await cleanup_client.delete_collection(collection)
            await cleanup_client.close()

    asyncio.run(exercise_qdrant())

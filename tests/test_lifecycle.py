from typing import cast

from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.core.config import Settings
from app.main import create_app
from tests.embeddings import DeterministicEmbeddingProvider
from tests.llm import FakeLLMProvider
from tests.queue import InMemoryIngestionQueue
from tests.rag import FakeQueryRewriter, FakeReranker
from tests.storage import InMemoryObjectStorage
from tests.vector_store import InMemoryVectorStore


class ClosableRedis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_application_shutdown_closes_owned_resources() -> None:
    storage = InMemoryObjectStorage()
    queue = InMemoryIngestionQueue()
    embedding_provider = DeterministicEmbeddingProvider()
    vector_store = InMemoryVectorStore()
    llm_provider = FakeLLMProvider()
    query_rewriter = FakeQueryRewriter()
    reranker = FakeReranker()
    redis = ClosableRedis()
    application = create_app(
        Settings(environment="test", _env_file=None),
        object_storage=storage,
        ingestion_queue=queue,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        llm_provider=llm_provider,
        query_rewriter=query_rewriter,
        reranker=reranker,
        redis_client=cast(Redis, redis),
    )

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200

    assert storage.closed is True
    assert queue.closed is True
    assert embedding_provider.closed is True
    assert vector_store.closed is True
    assert llm_provider.closed is True
    assert query_rewriter.closed is True
    assert reranker.closed is True
    assert redis.closed is True

import asyncio

from app.embeddings.cached import CachedQueryEmbeddingProvider


class CountingEmbeddingProvider:
    def __init__(self) -> None:
        self.query_calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        del text
        self.query_calls += 1
        return [1.0, 0.0]

    async def close(self) -> None:
        pass


class InMemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.keys: list[str] = []

    async def get(self, key: str) -> str | None:
        self.keys.append(key)
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        del ex
        self.values[key] = value


def test_query_embeddings_are_cached_without_plaintext_keys() -> None:
    async def run() -> None:
        provider = CountingEmbeddingProvider()
        redis = InMemoryRedis()
        cached = CachedQueryEmbeddingProvider(
            provider,
            redis,  # type: ignore[arg-type]
            "test-model",
            dimensions=2,
            ttl_seconds=60,
        )

        first = await cached.embed_query("What is internal-system-42?")
        second = await cached.embed_query("What is internal-system-42?")

        assert first == second == [1.0, 0.0]
        assert provider.query_calls == 1
        assert all("internal-system-42" not in key for key in redis.keys)

    asyncio.run(run())

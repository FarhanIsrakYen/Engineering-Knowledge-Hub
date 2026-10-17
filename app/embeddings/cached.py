import json
import logging
from hashlib import sha256

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class CachedQueryEmbeddingProvider:
    def __init__(
        self,
        provider: EmbeddingProvider,
        redis: Redis,
        namespace: str,
        dimensions: int,
        ttl_seconds: int,
    ) -> None:
        self._provider = provider
        self._redis = redis
        self._namespace = namespace
        self._dimensions = dimensions
        self._ttl_seconds = ttl_seconds

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._provider.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        if self._ttl_seconds == 0:
            return await self._provider.embed_query(text)

        digest = sha256(text.encode("utf-8")).hexdigest()
        key = f"ekh:query-embedding:{self._namespace}:{digest}"
        try:
            cached = await self._redis.get(key)
            if cached is not None:
                vector = [float(value) for value in json.loads(cached)]
                if len(vector) == self._dimensions:
                    logger.debug(
                        "Query embedding cache hit",
                        extra={"cache_event": "hit"},
                    )
                    return vector
        except (RedisError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning(
                "Query embedding cache read failed",
                extra={"cache_event": "read_error"},
            )

        vector = await self._provider.embed_query(text)
        try:
            await self._redis.set(key, json.dumps(vector), ex=self._ttl_seconds)
        except RedisError:
            logger.warning(
                "Query embedding cache write failed",
                extra={"cache_event": "write_error"},
            )
        return vector

    async def close(self) -> None:
        await self._provider.close()

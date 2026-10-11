import asyncio
from collections.abc import Callable, Iterable
from typing import Any

from fastembed import TextEmbedding

from app.embeddings.base import EmbeddingProviderError


class FastEmbedEmbeddingProvider:
    def __init__(
        self,
        model_name: str,
        dimensions: int,
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._cache_dir = cache_dir
        self._model: TextEmbedding | None = None
        self._load_lock = asyncio.Lock()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_model()
        return await self._embed(lambda: model.passage_embed(texts))

    async def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingProviderError("The embedding query cannot be empty")
        model = await self._get_model()
        embeddings = await self._embed(lambda: model.query_embed([text]))
        return embeddings[0]

    async def _get_model(self) -> TextEmbedding:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(
                        TextEmbedding,
                        model_name=self._model_name,
                        cache_dir=self._cache_dir,
                        lazy_load=True,
                    )
                except Exception as exc:
                    raise EmbeddingProviderError(
                        "The embedding model could not be loaded"
                    ) from exc
        return self._model

    async def _embed(
        self,
        create_embeddings: Callable[[], Iterable[Any]],
    ) -> list[list[float]]:
        try:
            vectors = await asyncio.to_thread(
                lambda: [
                    vector.tolist() for vector in create_embeddings()
                ]
            )
        except Exception as exc:
            raise EmbeddingProviderError(
                "The embedding provider could not generate vectors"
            ) from exc
        if any(len(vector) != self._dimensions for vector in vectors):
            raise EmbeddingProviderError(
                "The embedding model dimensions do not match configuration"
            )
        return vectors

    async def close(self) -> None:
        return None

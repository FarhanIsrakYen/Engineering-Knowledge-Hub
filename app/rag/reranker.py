import asyncio
from typing import Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder


class RerankerError(Exception):
    pass


class Reranker(Protocol):
    async def score(self, query: str, documents: list[str]) -> list[float]: ...

    async def close(self) -> None: ...


class FastEmbedReranker:
    def __init__(
        self,
        model_name: str,
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: TextCrossEncoder | None = None
        self._load_lock = asyncio.Lock()

    async def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        model = await self._get_model()
        try:
            scores = await asyncio.to_thread(
                lambda: list(model.rerank(query, documents))
            )
        except Exception as exc:
            raise RerankerError("Reranking failed") from exc
        if len(scores) != len(documents):
            raise RerankerError("Reranker returned an invalid score count")
        return [float(score) for score in scores]

    async def _get_model(self) -> TextCrossEncoder:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(
                        TextCrossEncoder,
                        model_name=self._model_name,
                        cache_dir=self._cache_dir,
                        lazy_load=True,
                    )
                except Exception as exc:
                    raise RerankerError(
                        "The reranking model could not be loaded"
                    ) from exc
        return self._model

    async def close(self) -> None:
        return None

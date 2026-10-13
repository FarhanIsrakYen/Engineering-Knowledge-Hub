import math

from app.embeddings import EmbeddingProviderError


class DeterministicEmbeddingProvider:
    def __init__(self, *, dimensions: int = 3, fail: bool = False) -> None:
        self.dimensions = dimensions
        self.fail = fail
        self.closed = False

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingProviderError("Embedding failed")
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        if self.fail:
            raise EmbeddingProviderError("Embedding failed")
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        lower = text.lower()
        values = [
            float(lower.count("postgres") + lower.count("database")),
            float(lower.count("redis") + lower.count("cache")),
            1.0,
        ]
        magnitude = math.sqrt(sum(value * value for value in values))
        vector = [value / magnitude for value in values]
        if self.dimensions < len(vector):
            return vector[: self.dimensions]
        return vector + [0.0] * (self.dimensions - len(vector))

    async def close(self) -> None:
        self.closed = True

from app.rag import ConversationTurn, QueryRewriterError, RerankerError


class FakeQueryRewriter:
    def __init__(self, rewritten_query: str | None = None) -> None:
        self.rewritten_query = rewritten_query
        self.fail = False
        self.calls: list[tuple[str, list[ConversationTurn] | None]] = []
        self.closed = False

    async def rewrite(
        self,
        question: str,
        history: list[ConversationTurn] | None = None,
    ) -> str:
        self.calls.append((question, history))
        if self.fail:
            raise QueryRewriterError("Rewrite failed")
        return self.rewritten_query or question

    async def close(self) -> None:
        self.closed = True


class FakeReranker:
    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = scores
        self.fail = False
        self.calls: list[tuple[str, list[str]]] = []
        self.closed = False

    async def score(self, query: str, documents: list[str]) -> list[float]:
        self.calls.append((query, documents))
        if self.fail:
            raise RerankerError("Reranking failed")
        if self.scores is not None:
            return self.scores
        return [float(len(documents) - index) for index in range(len(documents))]

    async def close(self) -> None:
        self.closed = True

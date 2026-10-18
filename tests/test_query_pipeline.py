import asyncio
from uuid import UUID, uuid4

from app.rag import ConversationTurn
from app.services.query import QueryService
from app.services.retrieval import RetrievedChunk
from tests.llm import FakeLLMProvider
from tests.rag import FakeQueryRewriter, FakeReranker


class FakeRetrievalService:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[UUID, str, int]] = []

    async def search(
        self,
        workspace_id: UUID,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        self.calls.append((workspace_id, query, limit))
        return self.chunks[:limit]


def _chunk(filename: str, text: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename=filename,
        chunk_index=0,
        text=text,
        page_number=None,
        section_title=None,
        score=score,
        vector_score=score,
        matched_lexically=True,
    )


def test_reranking_can_change_candidate_order() -> None:
    workspace_id = uuid4()
    initially_first = _chunk("first.txt", "Initial retrieval winner", 0.9)
    reranked_first = _chunk("second.txt", "Better answer after reranking", 0.8)
    retrieval = FakeRetrievalService([initially_first, reranked_first])
    rewriter = FakeQueryRewriter("rewritten retrieval query")
    reranker = FakeReranker([0.1, 0.95])
    llm = FakeLLMProvider("Grounded answer [S1].")
    service = QueryService(
        retrieval,
        llm,
        0.5,
        rewriter,
        reranker,
        rewriting_enabled=True,
        reranking_enabled=True,
        candidate_count=10,
    )

    result = asyncio.run(
        service.query(workspace_id, "Original user question", top_k=1)
    )

    assert retrieval.calls == [(workspace_id, "rewritten retrieval query", 10)]
    assert reranker.calls == [
        (
            "rewritten retrieval query",
            ["Initial retrieval winner", "Better answer after reranking"],
        )
    ]
    assert result.sources[0].document_id == reranked_first.document_id
    assert result.sources[0].score == 0.95
    _, generation_prompt = llm.calls[-1]
    assert "Original user question" in generation_prompt
    assert "Better answer after reranking" in generation_prompt
    assert "Initial retrieval winner" not in generation_prompt


def test_query_rewriting_can_be_disabled() -> None:
    workspace_id = uuid4()
    retrieval = FakeRetrievalService(
        [_chunk("source.txt", "Relevant source text", 0.9)]
    )
    rewriter = FakeQueryRewriter("this must not be used")
    reranker = FakeReranker()
    llm = FakeLLMProvider()
    service = QueryService(
        retrieval,
        llm,
        0.5,
        rewriter,
        reranker,
        rewriting_enabled=False,
        reranking_enabled=False,
        candidate_count=12,
    )

    asyncio.run(service.query(workspace_id, "Original question", top_k=1))

    assert rewriter.calls == []
    assert reranker.calls == []
    assert retrieval.calls == [(workspace_id, "Original question", 12)]


def test_conversation_history_is_compacted_into_standalone_query() -> None:
    workspace_id = uuid4()
    retrieval = FakeRetrievalService(
        [_chunk("source.txt", "PostgreSQL durability details", 0.9)]
    )
    rewriter = FakeQueryRewriter("PostgreSQL durability")
    reranker = FakeReranker()
    llm = FakeLLMProvider("It is durable [S1].")
    service = QueryService(
        retrieval,
        llm,
        0.5,
        rewriter,
        reranker,
        rewriting_enabled=False,
        reranking_enabled=False,
        candidate_count=10,
    )
    history = [
        ConversationTurn("user", "Tell me about PostgreSQL."),
        ConversationTurn("assistant", "HISTORY_ONLY_MARKER"),
    ]

    async def run_stream() -> str:
        prepared = await service.prepare(
            workspace_id,
            "What about its durability?",
            top_k=1,
            history=history,
        )
        parts = [part async for part in service.stream(prepared)]
        return "".join(parts)

    answer = asyncio.run(run_stream())

    assert answer == "It is durable [S1]."
    assert rewriter.calls == [("What about its durability?", history)]
    assert retrieval.calls == [(workspace_id, "PostgreSQL durability", 10)]
    _, prompt = llm.stream_calls[-1]
    assert "What about its durability?" in prompt
    assert "PostgreSQL durability" in prompt
    assert "HISTORY_ONLY_MARKER" not in prompt

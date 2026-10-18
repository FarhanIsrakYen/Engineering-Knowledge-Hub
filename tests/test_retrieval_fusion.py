from uuid import uuid4

from app.services.retrieval import LexicalSearchResult, RetrievalService
from app.vector import VectorSearchResult


def test_rrf_promotes_identifier_found_by_lexical_search() -> None:
    semantic_match = uuid4()
    identifier_match = uuid4()
    vector_results = [
        VectorSearchResult(
            chunk_id=uuid4(),
            document_id=semantic_match,
            chunk_index=0,
            score=0.91,
        ),
        VectorSearchResult(
            chunk_id=uuid4(),
            document_id=identifier_match,
            chunk_index=0,
            score=0.42,
        ),
    ]
    lexical_results = [
        LexicalSearchResult(
            document_id=identifier_match,
            chunk_index=0,
            score=0.1,
        )
    ]

    candidates = RetrievalService._rank_candidates(
        "hybrid",
        vector_results,
        lexical_results,
    )

    assert candidates[0].document_id == identifier_match
    assert candidates[0].matched_lexically is True
    assert candidates[0].vector_score == 0.42

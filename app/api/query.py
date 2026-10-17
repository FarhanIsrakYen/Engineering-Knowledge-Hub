from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    enforce_expensive_query_rate_limit,
    get_embedding_provider,
    get_llm_provider,
    get_query_rewriter,
    get_reranker,
    get_vector_store,
    get_workspace_context,
)
from app.db.session import get_db_session
from app.embeddings import EmbeddingProvider
from app.llm import LLMProvider
from app.rag import QueryRewriter, Reranker
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query import build_query_service
from app.services.tenancy import WorkspaceContext
from app.vector import VectorStore

router = APIRouter(tags=["query"])


@router.post(
    "/workspaces/{workspace_id}/query",
    response_model=QueryResponse,
)
async def query_workspace(
    payload: QueryRequest,
    request: Request,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embedding_provider: Annotated[
        EmbeddingProvider,
        Depends(get_embedding_provider),
    ],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    query_rewriter: Annotated[QueryRewriter, Depends(get_query_rewriter)],
    reranker: Annotated[Reranker, Depends(get_reranker)],
    _: Annotated[None, Depends(enforce_expensive_query_rate_limit)],
) -> QueryResponse:
    result = await build_query_service(
        session,
        embedding_provider,
        vector_store,
        llm_provider,
        query_rewriter,
        reranker,
        request.app.state.settings,
    ).query(
        context.workspace.id,
        payload.question,
        payload.top_k or request.app.state.settings.rag_default_top_k,
    )
    return QueryResponse.model_validate(result)

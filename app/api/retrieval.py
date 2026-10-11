from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_embedding_provider,
    get_vector_store,
    get_workspace_context,
)
from app.db.session import get_db_session
from app.embeddings import EmbeddingProvider
from app.schemas.retrieval import SearchRequest, SearchResultResponse
from app.services.retrieval import RetrievalService
from app.services.tenancy import WorkspaceContext
from app.vector import VectorStore

router = APIRouter(tags=["retrieval"])


@router.post(
    "/workspaces/{workspace_id}/search",
    response_model=list[SearchResultResponse],
)
async def search_workspace(
    payload: SearchRequest,
    context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embedding_provider: Annotated[
        EmbeddingProvider,
        Depends(get_embedding_provider),
    ],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
) -> list[SearchResultResponse]:
    results = await RetrievalService(
        session,
        embedding_provider,
        vector_store,
    ).search(context.workspace.id, payload.query, payload.limit)
    return [SearchResultResponse.model_validate(result) for result in results]

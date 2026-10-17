from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    enforce_expensive_query_rate_limit,
    get_answer_evaluator,
    get_current_user,
    get_embedding_provider,
    get_evaluation_context,
    get_evaluation_workspace_context,
    get_llm_provider,
    get_query_rewriter,
    get_reranker,
    get_vector_store,
)
from app.db.session import get_db_session
from app.embeddings import EmbeddingProvider
from app.evaluation import AnswerEvaluator
from app.llm import LLMProvider
from app.models.user import User
from app.rag import QueryRewriter, Reranker
from app.schemas.evaluation import EvaluationCreate, EvaluationRunResponse
from app.services.evaluation import EvaluationService, get_evaluation_run
from app.services.query import build_query_service
from app.services.tenancy import EvaluationContext, WorkspaceContext
from app.vector import VectorStore

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post(
    "",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation(
    payload: EvaluationCreate,
    request: Request,
    context: Annotated[
        WorkspaceContext,
        Depends(get_evaluation_workspace_context),
    ],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    embedding_provider: Annotated[
        EmbeddingProvider,
        Depends(get_embedding_provider),
    ],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
    query_rewriter: Annotated[QueryRewriter, Depends(get_query_rewriter)],
    reranker: Annotated[Reranker, Depends(get_reranker)],
    answer_evaluator: Annotated[
        AnswerEvaluator,
        Depends(get_answer_evaluator),
    ],
    _: Annotated[None, Depends(enforce_expensive_query_rate_limit)],
) -> EvaluationRunResponse:
    settings = request.app.state.settings
    query_service = build_query_service(
        session,
        embedding_provider,
        vector_store,
        llm_provider,
        query_rewriter,
        reranker,
        settings,
    )
    run = await EvaluationService(
        session,
        query_service,
        answer_evaluator,
    ).run(
        context.workspace.id,
        user.id,
        payload.dataset,
        payload.top_k or settings.rag_default_top_k,
        use_llm_judge=payload.use_llm_judge,
    )
    return EvaluationRunResponse.model_validate(run)


@router.get("/{run_id}", response_model=EvaluationRunResponse)
async def get_evaluation(
    context: Annotated[EvaluationContext, Depends(get_evaluation_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EvaluationRunResponse:
    run = await get_evaluation_run(session, context.run.id)
    return EvaluationRunResponse.model_validate(run)

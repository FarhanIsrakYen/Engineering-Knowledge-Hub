from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.core.security import AuthenticationError
from app.db.session import get_db_session
from app.embeddings import EmbeddingProvider
from app.evaluation import AnswerEvaluator
from app.ingestion.queue import IngestionQueue
from app.llm import LLMProvider
from app.models.user import User
from app.rag import QueryRewriter, Reranker
from app.schemas.evaluation import EvaluationCreate
from app.services.auth import get_user_for_token
from app.services.rate_limit import RateLimiter
from app.services.tenancy import (
    ConversationContext,
    DocumentContext,
    EvaluationContext,
    OrganizationContext,
    WorkspaceContext,
    require_document_delete_role,
    require_management_role,
    resolve_conversation_context,
    resolve_document_context,
    resolve_evaluation_context,
    resolve_organization_context,
    resolve_workspace_context,
)
from app.storage import ObjectStorage
from app.vector import VectorStore

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    return await get_user_for_token(
        session,
        credentials.credentials,
        "access",
        request.app.state.settings,
    )


async def get_organization_context(
    organization_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationContext:
    return await resolve_organization_context(session, organization_id, user.id)


async def get_managed_organization_context(
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
) -> OrganizationContext:
    return require_management_role(context)


async def get_workspace_context(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkspaceContext:
    return await resolve_workspace_context(session, workspace_id, user.id)


async def get_document_context(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentContext:
    return await resolve_document_context(session, document_id, user.id)


async def get_conversation_context(
    conversation_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationContext:
    return await resolve_conversation_context(
        session,
        conversation_id,
        user.id,
    )


async def get_evaluation_workspace_context(
    payload: EvaluationCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkspaceContext:
    return await resolve_workspace_context(
        session,
        payload.workspace_id,
        user.id,
    )


async def get_evaluation_context(
    run_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EvaluationContext:
    return await resolve_evaluation_context(session, run_id, user.id)


async def get_deletable_document_context(
    context: Annotated[DocumentContext, Depends(get_document_context)],
) -> DocumentContext:
    return require_document_delete_role(context)


def get_object_storage(request: Request) -> ObjectStorage:
    return request.app.state.object_storage


def get_ingestion_queue(request: Request) -> IngestionQueue:
    return request.app.state.ingestion_queue


def get_embedding_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider


def get_vector_store(request: Request) -> VectorStore:
    return request.app.state.vector_store


def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm_provider


def get_query_rewriter(request: Request) -> QueryRewriter:
    return request.app.state.query_rewriter


def get_reranker(request: Request) -> Reranker:
    return request.app.state.reranker


def get_answer_evaluator(request: Request) -> AnswerEvaluator:
    return request.app.state.answer_evaluator


async def enforce_expensive_query_rate_limit(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    settings = request.app.state.settings
    limiter: RateLimiter = request.app.state.rate_limiter
    result = await limiter.check(
        f"rag-query:{user.id}",
        settings.query_rate_limit_requests,
        settings.query_rate_limit_window_seconds,
    )
    if not result.allowed:
        raise ApplicationError(
            "Query rate limit exceeded",
            code="rate_limit_exceeded",
            status_code=429,
            headers={"Retry-After": str(result.retry_after_seconds)},
        )

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import (
    enforce_expensive_query_rate_limit,
    get_conversation_context,
    get_current_user,
    get_embedding_provider,
    get_llm_provider,
    get_query_rewriter,
    get_reranker,
    get_vector_store,
    get_workspace_context,
)
from app.core.exceptions import ApplicationError
from app.db.session import get_db_session
from app.embeddings import EmbeddingProvider
from app.llm import LLMProvider
from app.models.conversation import Message
from app.models.user import User
from app.rag import QueryRewriter, Reranker
from app.schemas.conversation import (
    ConversationMessageRequest,
    ConversationResponse,
    MessageResponse,
)
from app.services.conversation import ConversationService
from app.services.query import QueryService, build_query_service
from app.services.tenancy import ConversationContext, WorkspaceContext
from app.vector import VectorStore

router = APIRouter(tags=["conversations"])
logger = logging.getLogger(__name__)


@router.post(
    "/workspaces/{workspace_id}/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    context: Annotated[WorkspaceContext, Depends(get_workspace_context)],
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationResponse:
    conversation = await ConversationService(session).create(
        context.workspace.id,
        user.id,
    )
    return ConversationResponse.model_validate(
        {
            "id": conversation.id,
            "workspace_id": conversation.workspace_id,
            "user_id": conversation.user_id,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "messages": [],
        }
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    context: Annotated[ConversationContext, Depends(get_conversation_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationResponse:
    messages = await ConversationService(session).list_messages(
        context.conversation.id
    )
    return ConversationResponse.model_validate(
        {
            "id": context.conversation.id,
            "workspace_id": context.conversation.workspace_id,
            "user_id": context.conversation.user_id,
            "created_at": context.conversation.created_at,
            "updated_at": context.conversation.updated_at,
            "messages": [_message_response(message) for message in messages],
        }
    )


@router.post("/conversations/{conversation_id}/messages")
async def create_message(
    payload: ConversationMessageRequest,
    request: Request,
    context: Annotated[ConversationContext, Depends(get_conversation_context)],
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
) -> StreamingResponse:
    settings = request.app.state.settings
    turn = await ConversationService(session).start_turn(
        context.conversation,
        payload.content,
        settings.conversation_history_messages,
    )
    top_k = payload.top_k or settings.rag_default_top_k
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.db_session_factory
    )

    async def event_stream() -> AsyncIterator[str]:
        if await request.is_disconnected():
            return
        query_service: QueryService
        answer_stream: AsyncGenerator[str, None] | None = None
        try:
            async with session_factory() as retrieval_session:
                query_service = build_query_service(
                    retrieval_session,
                    embedding_provider,
                    vector_store,
                    llm_provider,
                    query_rewriter,
                    reranker,
                    settings,
                )
                prepared = await query_service.prepare(
                    turn.workspace_id,
                    turn.question,
                    top_k,
                    turn.history,
                )

            answer_parts: list[str] = []
            answer_stream = query_service.stream(prepared)
            async for delta in answer_stream:
                if await request.is_disconnected():
                    await answer_stream.aclose()
                    return
                answer_parts.append(delta)
                yield _sse("delta", {"text": delta})

            answer = "".join(answer_parts).strip()
            if not answer:
                raise ApplicationError(
                    "The answer generation service returned an empty response",
                    code="llm_provider_unavailable",
                    status_code=503,
                )
            sources = query_service.sources(prepared)
            assistant_message = await ConversationService.complete_turn(
                session_factory,
                turn.conversation_id,
                answer,
                sources,
            )
            if await request.is_disconnected():
                return
            message_response = _message_response(assistant_message)
            yield _sse(
                "sources",
                {
                    "sources": [
                        source.model_dump(mode="json")
                        for source in (message_response.sources or [])
                    ],
                },
            )
            yield _sse(
                "done",
                message_response.model_dump(mode="json"),
            )
        except asyncio.CancelledError:
            if answer_stream is not None:
                await answer_stream.aclose()
            raise
        except ApplicationError as exc:
            yield _sse(
                "error",
                {"code": exc.code, "message": exc.message},
            )
        except Exception:
            logger.exception(
                "Conversation response stream failed",
                extra={"conversation_id": str(turn.conversation_id)},
            )
            yield _sse(
                "error",
                {
                    "code": "conversation_stream_failed",
                    "message": "The conversation response could not be completed",
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _message_response(message: Message) -> MessageResponse:
    return MessageResponse.model_validate(
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "sources": message.sources,
            "created_at": message.created_at,
        }
    )


def _sse(event: str, data: Any) -> str:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

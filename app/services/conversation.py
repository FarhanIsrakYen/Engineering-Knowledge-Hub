from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.conversation import Conversation, Message
from app.rag import ConversationTurn
from app.services.query import QuerySource


@dataclass(frozen=True, slots=True)
class ConversationTurnContext:
    conversation_id: UUID
    workspace_id: UUID
    question: str
    history: list[ConversationTurn]


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> Conversation:
        conversation = Conversation(workspace_id=workspace_id, user_id=user_id)
        self._session.add(conversation)
        await self._session.commit()
        await self._session.refresh(conversation)
        return conversation

    async def list_messages(self, conversation_id: UUID) -> list[Message]:
        messages = await self._session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        return list(messages)

    async def start_turn(
        self,
        conversation: Conversation,
        content: str,
        history_limit: int,
    ) -> ConversationTurnContext:
        recent = await self._session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(history_limit * 2)
        )
        history = self._completed_history(
            list(reversed(list(recent))),
            history_limit,
        )
        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            content=content.strip(),
            sources=None,
        )
        conversation.updated_at = datetime.now(UTC)
        self._session.add(user_message)
        await self._session.commit()
        return ConversationTurnContext(
            conversation_id=conversation.id,
            workspace_id=conversation.workspace_id,
            question=user_message.content,
            history=history,
        )

    @staticmethod
    async def complete_turn(
        session_factory: async_sessionmaker[AsyncSession],
        conversation_id: UUID,
        content: str,
        sources: list[QuerySource],
    ) -> Message:
        source_data: list[dict[str, Any]] = [
            {
                "document_id": str(source.document_id),
                "filename": source.filename,
                "page": source.page,
                "chunk_id": str(source.chunk_id),
                "score": source.score,
            }
            for source in sources
        ]
        async with session_factory() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                raise RuntimeError("Conversation disappeared during generation")
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                sources=source_data,
            )
            conversation.updated_at = datetime.now(UTC)
            session.add(assistant_message)
            await session.commit()
            await session.refresh(assistant_message)
            return assistant_message

    @staticmethod
    def _completed_history(
        messages: list[Message],
        history_limit: int,
    ) -> list[ConversationTurn]:
        completed: list[ConversationTurn] = []
        pending_user: Message | None = None
        for message in messages:
            if message.role == "user":
                pending_user = message
            elif pending_user is not None:
                completed.extend(
                    (
                        ConversationTurn("user", pending_user.content),
                        ConversationTurn("assistant", message.content),
                    )
                )
                pending_user = None
        return completed[-history_limit:]

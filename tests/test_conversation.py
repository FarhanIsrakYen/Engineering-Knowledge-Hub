from uuid import uuid4

from app.models.conversation import Message
from app.services.conversation import ConversationService


def _message(role: str, content: str) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content=content,
        sources=None,
    )


def test_history_uses_only_recent_completed_turns() -> None:
    messages = [
        _message("user", "old question"),
        _message("assistant", "old answer"),
        _message("user", "recent question"),
        _message("assistant", "recent answer"),
        _message("user", "failed unanswered question"),
    ]

    history = ConversationService._completed_history(messages, 2)

    assert [(turn.role, turn.content) for turn in history] == [
        ("user", "recent question"),
        ("assistant", "recent answer"),
    ]

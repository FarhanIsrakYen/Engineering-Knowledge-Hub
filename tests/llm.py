from collections.abc import AsyncIterator

from app.llm import LLMProviderError


class FakeLLMProvider:
    def __init__(
        self,
        response: str = "PostgreSQL stores durable application data [S1].",
    ) -> None:
        self.response = response
        self.fail = False
        self.calls: list[tuple[str, str]] = []
        self.stream_calls: list[tuple[str, str]] = []
        self.closed = False

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.fail:
            raise LLMProviderError("LLM failed")
        return self.response

    async def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[str]:
        self.stream_calls.append((system_prompt, user_prompt))
        if self.fail:
            raise LLMProviderError("LLM failed")
        midpoint = max(1, len(self.response) // 2)
        yield self.response[:midpoint]
        yield self.response[midpoint:]

    async def close(self) -> None:
        self.closed = True

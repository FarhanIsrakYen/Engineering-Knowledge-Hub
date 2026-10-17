from collections.abc import AsyncIterator
from typing import Protocol


class LLMProviderError(Exception):
    pass


class LLMProvider(Protocol):
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...

    def stream(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> AsyncIterator[str]: ...

    async def close(self) -> None: ...

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

    async def close(self) -> None: ...

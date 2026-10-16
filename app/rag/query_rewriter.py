from typing import Protocol

from app.llm import LLMProvider, LLMProviderError

REWRITE_SYSTEM_PROMPT = """Rewrite the user's question as one concise search query.
Preserve technical identifiers, product names, error codes, and configuration keys exactly.
Return only the rewritten query without commentary or quotation marks."""


class QueryRewriterError(Exception):
    pass


class QueryRewriter(Protocol):
    async def rewrite(self, question: str) -> str: ...

    async def close(self) -> None: ...


class LLMQueryRewriter:
    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm_provider = llm_provider

    async def rewrite(self, question: str) -> str:
        try:
            rewritten = await self._llm_provider.generate(
                system_prompt=REWRITE_SYSTEM_PROMPT,
                user_prompt=question,
            )
        except LLMProviderError as exc:
            raise QueryRewriterError("Query rewriting failed") from exc

        rewritten = rewritten.strip()
        if not rewritten:
            raise QueryRewriterError("Query rewriting returned an empty query")
        return rewritten

    async def close(self) -> None:
        # The application owns and closes the shared LLM provider.
        return None

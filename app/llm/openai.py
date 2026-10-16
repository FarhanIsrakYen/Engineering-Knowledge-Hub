from openai import AsyncOpenAI, OpenAIError

from app.llm.base import LLMProviderError


class OpenAILLMProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 800,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._client: AsyncOpenAI | None = None

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if not self._api_key:
            raise LLMProviderError("The LLM provider is not configured")

        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )

        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=system_prompt,
                input=user_prompt,
                max_output_tokens=self._max_output_tokens,
                store=False,
            )
        except OpenAIError as exc:
            raise LLMProviderError("The LLM provider request failed") from exc

        answer = response.output_text.strip()
        if not answer:
            raise LLMProviderError("The LLM provider returned an empty response")
        return answer

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

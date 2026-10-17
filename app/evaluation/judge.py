import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from app.llm import LLMProvider, LLMProviderError


class EvaluationJudgeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AnswerJudgment:
    answer_relevance: float
    groundedness: float
    reason: str


class AnswerEvaluator(Protocol):
    async def evaluate(
        self,
        *,
        question: str,
        expected_answer: str,
        actual_answer: str,
        contexts: list[str],
    ) -> AnswerJudgment: ...


class _JudgeOutput(BaseModel):
    answer_relevance: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=2000)


class LLMAnswerEvaluator:
    _SYSTEM_PROMPT = """You evaluate this application's RAG answers.
Return only JSON with answer_relevance, groundedness, and reason.
Scores must be numbers from 0 to 1. Answer relevance compares the actual answer
to the question and expected answer. Groundedness measures whether every material
claim in the actual answer is supported by the supplied retrieved context. Do not
reward style, length, or confidence. Penalize unsupported claims explicitly."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def evaluate(
        self,
        *,
        question: str,
        expected_answer: str,
        actual_answer: str,
        contexts: list[str],
    ) -> AnswerJudgment:
        prompt = (
            f"Question:\n{question}\n\n"
            f"Expected answer:\n{expected_answer}\n\n"
            f"Actual answer:\n{actual_answer}\n\n"
            "Retrieved context:\n"
            + "\n\n".join(contexts)
        )
        try:
            raw = await self._provider.generate(
                system_prompt=self._SYSTEM_PROMPT,
                user_prompt=prompt,
            )
            parsed = _JudgeOutput.model_validate(json.loads(raw))
        except (LLMProviderError, json.JSONDecodeError, ValidationError) as exc:
            raise EvaluationJudgeError(
                "The LLM judge returned an invalid evaluation"
            ) from exc
        return AnswerJudgment(
            answer_relevance=parsed.answer_relevance,
            groundedness=parsed.groundedness,
            reason=parsed.reason,
        )

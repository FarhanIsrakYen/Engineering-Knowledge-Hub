from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ApplicationError
from app.evaluation import (
    AnswerEvaluator,
    EvaluationJudgeError,
    calculate_retrieval_metrics,
)
from app.evaluation.metrics import mean
from app.models.evaluation import EvaluationResult, EvaluationRun
from app.schemas.evaluation import EvaluationDatasetItem
from app.services.query import QueryService


class EvaluationService:
    def __init__(
        self,
        session: AsyncSession,
        query_service: QueryService,
        answer_evaluator: AnswerEvaluator,
    ) -> None:
        self._session = session
        self._query_service = query_service
        self._answer_evaluator = answer_evaluator

    async def run(
        self,
        workspace_id: UUID,
        created_by: UUID | None,
        dataset: list[EvaluationDatasetItem],
        top_k: int,
        *,
        use_llm_judge: bool,
    ) -> EvaluationRun:
        run = EvaluationRun(
            workspace_id=workspace_id,
            created_by=created_by,
            top_k=top_k,
            llm_judge_enabled=use_llm_judge,
            item_count=len(dataset),
        )
        self._session.add(run)
        await self._session.commit()

        results: list[EvaluationResult] = []
        try:
            for item_index, item in enumerate(dataset):
                query_result = await self._query_service.query(
                    workspace_id,
                    item.question,
                    top_k,
                )
                retrieved_document_ids = _unique_document_ids(
                    [source.document_id for source in query_result.sources]
                )
                metrics = calculate_retrieval_metrics(
                    item.expected_document_ids,
                    retrieved_document_ids,
                    top_k,
                )
                answer_relevance: float | None = None
                groundedness: float | None = None
                judge_reason: str | None = None
                if use_llm_judge:
                    judgment = await self._answer_evaluator.evaluate(
                        question=item.question,
                        expected_answer=item.expected_answer,
                        actual_answer=query_result.answer,
                        contexts=query_result.context_texts,
                    )
                    answer_relevance = judgment.answer_relevance
                    groundedness = judgment.groundedness
                    judge_reason = judgment.reason

                timings = query_result.timings
                result = EvaluationResult(
                    run_id=run.id,
                    item_index=item_index,
                    question=item.question,
                    expected_answer=item.expected_answer,
                    expected_document_ids=[
                        str(document_id)
                        for document_id in item.expected_document_ids
                    ],
                    retrieved_document_ids=[
                        str(document_id)
                        for document_id in retrieved_document_ids
                    ],
                    answer=query_result.answer,
                    hit_rate_at_k=metrics.hit_rate_at_k,
                    recall_at_k=metrics.recall_at_k,
                    reciprocal_rank=metrics.reciprocal_rank,
                    retrieval_latency_ms=timings["query_retrieval_latency_ms"],
                    generation_latency_ms=timings["generation_latency_ms"],
                    total_latency_ms=timings["total_latency_ms"],
                    answer_relevance=answer_relevance,
                    groundedness=groundedness,
                    judge_reason=judge_reason,
                )
                self._session.add(result)
                results.append(result)

            run.status = "completed"
            run.metrics = _aggregate_metrics(results, use_llm_judge)
            run.completed_at = datetime.now(UTC)
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            stored_run = await self._session.get(EvaluationRun, run.id)
            if stored_run is None:
                raise
            stored_run.status = "failed"
            stored_run.failure_reason = _failure_reason(exc)
            stored_run.completed_at = datetime.now(UTC)
            await self._session.commit()

        return await get_evaluation_run(self._session, run.id)


async def get_evaluation_run(
    session: AsyncSession,
    run_id: UUID,
) -> EvaluationRun:
    run = await session.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == run_id)
        .options(selectinload(EvaluationRun.results))
    )
    if run is None:
        raise ApplicationError(
            "Evaluation run not found",
            code="evaluation_run_not_found",
            status_code=404,
        )
    return run


def _unique_document_ids(document_ids: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(document_ids))


def _aggregate_metrics(
    results: list[EvaluationResult],
    include_llm_judge: bool,
) -> dict[str, object]:
    llm_judged: dict[str, float] | None = None
    if include_llm_judge:
        llm_judged = {
            "answer_relevance": mean(
                [
                    result.answer_relevance
                    for result in results
                    if result.answer_relevance is not None
                ]
            ),
            "groundedness": mean(
                [
                    result.groundedness
                    for result in results
                    if result.groundedness is not None
                ]
            ),
        }
    return {
        "deterministic": {
            "hit_rate_at_k": mean(
                [result.hit_rate_at_k for result in results]
            ),
            "recall_at_k": mean([result.recall_at_k for result in results]),
            "mrr": mean([result.reciprocal_rank for result in results]),
        },
        "system": {
            "retrieval_latency_ms": mean(
                [result.retrieval_latency_ms for result in results]
            ),
            "generation_latency_ms": mean(
                [result.generation_latency_ms for result in results]
            ),
            "total_latency_ms": mean(
                [result.total_latency_ms for result in results]
            ),
        },
        "llm_judged": llm_judged,
    }


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, ApplicationError):
        return exc.message
    if isinstance(exc, EvaluationJudgeError):
        return str(exc)
    return "Evaluation execution failed"

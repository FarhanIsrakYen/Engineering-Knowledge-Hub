from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_evaluation_runs_status",
        ),
        Index(
            "ix_evaluation_runs_workspace_created_at",
            "workspace_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
    )
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_judge_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    results: Mapped[list["EvaluationResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EvaluationResult.item_index",
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        CheckConstraint(
            "item_index >= 0",
            name="ck_evaluation_results_item_index_nonnegative",
        ),
        Index(
            "ix_evaluation_results_run_item",
            "run_id",
            "item_index",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    expected_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    retrieved_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    hit_rate_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    recall_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    reciprocal_rank: Mapped[float] = mapped_column(Float, nullable=False)
    retrieval_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    generation_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    answer_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    groundedness: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    run: Mapped[EvaluationRun] = relationship(back_populates="results")

"""Add evaluation runs and results.

Revision ID: 20261017_0007
Revises: 20261017_0006
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_0007"
down_revision: str | Sequence[str] | None = "20261017_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="running",
            nullable=False,
        ),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column(
            "llm_judge_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_evaluation_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_workspace_created_at",
        "evaluation_runs",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=False),
        sa.Column("expected_document_ids", sa.JSON(), nullable=False),
        sa.Column("retrieved_document_ids", sa.JSON(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("hit_rate_at_k", sa.Float(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=False),
        sa.Column("reciprocal_rank", sa.Float(), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=False),
        sa.Column("generation_latency_ms", sa.Float(), nullable=False),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("answer_relevance", sa.Float(), nullable=True),
        sa.Column("groundedness", sa.Float(), nullable=True),
        sa.Column("judge_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "item_index >= 0",
            name="ck_evaluation_results_item_index_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_results_run_item",
        "evaluation_results",
        ["run_id", "item_index"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_results_run_item",
        table_name="evaluation_results",
    )
    op.drop_table("evaluation_results")
    op.drop_index(
        "ix_evaluation_runs_workspace_created_at",
        table_name="evaluation_runs",
    )
    op.drop_table("evaluation_runs")

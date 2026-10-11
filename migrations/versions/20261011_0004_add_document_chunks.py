"""Add document chunks.

Revision ID: 20261011_0004
Revises: 20261008_0003
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261011_0004"
down_revision: str | Sequence[str] | None = "20261008_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_index_nonnegative",
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_document_chunks_page_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "chunk_index"),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")

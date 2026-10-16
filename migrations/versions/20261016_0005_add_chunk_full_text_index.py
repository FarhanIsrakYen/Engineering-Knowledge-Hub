"""Add full-text search index for document chunks.

Revision ID: 20261016_0005
Revises: 20261011_0004
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_0005"
down_revision: str | Sequence[str] | None = "20261011_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_document_chunks_text_search "
        "ON document_chunks USING gin (to_tsvector('english', text))"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_text_search",
        table_name="document_chunks",
    )

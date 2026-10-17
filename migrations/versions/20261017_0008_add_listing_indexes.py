"""Add indexes for ordered workspace and document listings.

Revision ID: 20261017_0008
Revises: 20261017_0007
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261017_0008"
down_revision: str | Sequence[str] | None = "20261017_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_workspaces_organization_created_at",
        "workspaces",
        ["organization_id", "created_at", "id"],
    )
    op.drop_index(
        "ix_documents_workspace_created_at",
        table_name="documents",
    )
    op.create_index(
        "ix_documents_workspace_created_at",
        "documents",
        ["workspace_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_documents_workspace_created_at",
        table_name="documents",
    )
    op.create_index(
        "ix_documents_workspace_created_at",
        "documents",
        ["workspace_id", "created_at"],
    )
    op.drop_index(
        "ix_workspaces_organization_created_at",
        table_name="workspaces",
    )

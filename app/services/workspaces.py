from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.models.organization import Organization
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate


async def create_workspace(
    session: AsyncSession,
    organization: Organization,
    data: WorkspaceCreate,
) -> Workspace:
    workspace = Workspace(
        organization_id=organization.id,
        name=data.name,
        description=data.description,
    )
    session.add(workspace)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "A workspace with this name already exists in the organization",
            code="workspace_name_exists",
            status_code=409,
        ) from exc

    await session.refresh(workspace)
    return workspace


async def list_organization_workspaces(
    session: AsyncSession,
    organization: Organization,
) -> list[Workspace]:
    workspaces = await session.scalars(
        select(Workspace)
        .where(Workspace.organization_id == organization.id)
        .order_by(Workspace.created_at, Workspace.id)
    )
    return list(workspaces)

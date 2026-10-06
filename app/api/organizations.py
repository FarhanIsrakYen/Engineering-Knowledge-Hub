from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_user,
    get_managed_organization_context,
    get_organization_context,
)
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationMemberAdd,
    OrganizationMemberResponse,
    OrganizationResponse,
)
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse
from app.services.organizations import (
    add_organization_member,
    create_organization,
    list_user_organizations,
)
from app.services.tenancy import OrganizationContext
from app.services.workspaces import (
    create_workspace,
    list_organization_workspaces,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    data: OrganizationCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationResponse:
    organization = await create_organization(session, user, data)
    return OrganizationResponse.model_validate(organization)


@router.get("", response_model=list[OrganizationResponse])
async def list_mine(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[OrganizationResponse]:
    organizations = await list_user_organizations(session, user)
    return [OrganizationResponse.model_validate(item) for item in organizations]


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    data: OrganizationMemberAdd,
    context: Annotated[
        OrganizationContext,
        Depends(get_managed_organization_context),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationMemberResponse:
    membership, user = await add_organization_member(
        session,
        context.organization,
        data,
    )
    return OrganizationMemberResponse(
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
    )


@router.post(
    "/{organization_id}/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization_workspace(
    data: WorkspaceCreate,
    context: Annotated[
        OrganizationContext,
        Depends(get_managed_organization_context),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkspaceResponse:
    workspace = await create_workspace(session, context.organization, data)
    return WorkspaceResponse.model_validate(workspace)


@router.get(
    "/{organization_id}/workspaces",
    response_model=list[WorkspaceResponse],
)
async def list_workspaces(
    context: Annotated[
        OrganizationContext,
        Depends(get_organization_context),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[WorkspaceResponse]:
    workspaces = await list_organization_workspaces(
        session,
        context.organization,
    )
    return [WorkspaceResponse.model_validate(item) for item in workspaces]

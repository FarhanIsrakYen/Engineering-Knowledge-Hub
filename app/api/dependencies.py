from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticationError
from app.db.session import get_db_session
from app.models.user import User
from app.services.auth import get_user_for_token
from app.services.tenancy import (
    OrganizationContext,
    require_management_role,
    resolve_organization_context,
)

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    return await get_user_for_token(
        session,
        credentials.credentials,
        "access",
        request.app.state.settings,
    )


async def get_organization_context(
    organization_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationContext:
    return await resolve_organization_context(session, organization_id, user.id)


async def get_managed_organization_context(
    context: Annotated[OrganizationContext, Depends(get_organization_context)],
) -> OrganizationContext:
    return require_management_role(context)

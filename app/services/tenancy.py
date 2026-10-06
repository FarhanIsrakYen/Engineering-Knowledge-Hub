from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.models.organization import Organization, OrganizationMember


@dataclass(frozen=True, slots=True)
class OrganizationContext:
    organization: Organization
    membership: OrganizationMember


async def resolve_organization_context(
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationContext:
    membership = await session.get(
        OrganizationMember,
        (organization_id, user_id),
    )
    if membership is None:
        raise ApplicationError(
            "Organization not found",
            code="organization_not_found",
            status_code=404,
        )

    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise ApplicationError(
            "Organization not found",
            code="organization_not_found",
            status_code=404,
        )
    return OrganizationContext(organization=organization, membership=membership)


def require_management_role(context: OrganizationContext) -> OrganizationContext:
    if context.membership.role not in {"owner", "admin"}:
        raise ApplicationError(
            "Insufficient organization permissions",
            code="insufficient_permissions",
            status_code=403,
        )
    return context

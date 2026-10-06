from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationMemberAdd


async def create_organization(
    session: AsyncSession,
    owner: User,
    data: OrganizationCreate,
) -> Organization:
    organization = Organization(name=data.name, slug=data.slug)
    session.add(organization)

    try:
        await session.flush()
        session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=owner.id,
                role="owner",
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "An organization with this slug already exists",
            code="organization_slug_exists",
            status_code=409,
        ) from exc

    await session.refresh(organization)
    return organization


async def list_user_organizations(
    session: AsyncSession,
    user: User,
) -> list[Organization]:
    organizations = await session.scalars(
        select(Organization)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(OrganizationMember.user_id == user.id)
        .order_by(Organization.created_at, Organization.id)
    )
    return list(organizations)


async def add_organization_member(
    session: AsyncSession,
    organization: Organization,
    data: OrganizationMemberAdd,
) -> tuple[OrganizationMember, User]:
    email = str(data.email).lower()
    user = await session.scalar(
        select(User).where(User.email == email, User.is_active.is_(True))
    )
    if user is None:
        raise ApplicationError(
            "User not found",
            code="user_not_found",
            status_code=404,
        )

    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=data.role,
    )
    session.add(membership)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApplicationError(
            "User is already a member of this organization",
            code="organization_member_exists",
            status_code=409,
        ) from exc
    return membership, user

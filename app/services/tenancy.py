from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApplicationError
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.evaluation import EvaluationRun
from app.models.organization import Organization, OrganizationMember
from app.models.workspace import Workspace


@dataclass(frozen=True, slots=True)
class OrganizationContext:
    organization: Organization
    membership: OrganizationMember


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    workspace: Workspace
    membership: OrganizationMember


@dataclass(frozen=True, slots=True)
class DocumentContext:
    document: Document
    membership: OrganizationMember


@dataclass(frozen=True, slots=True)
class ConversationContext:
    conversation: Conversation
    membership: OrganizationMember


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    run: EvaluationRun
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


async def resolve_workspace_context(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
) -> WorkspaceContext:
    result = await session.execute(
        select(Workspace, OrganizationMember)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Workspace.organization_id,
        )
        .where(
            Workspace.id == workspace_id,
            OrganizationMember.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise ApplicationError(
            "Workspace not found",
            code="workspace_not_found",
            status_code=404,
        )
    return WorkspaceContext(workspace=row[0], membership=row[1])


async def resolve_document_context(
    session: AsyncSession,
    document_id: UUID,
    user_id: UUID,
) -> DocumentContext:
    result = await session.execute(
        select(Document, OrganizationMember)
        .join(Workspace, Workspace.id == Document.workspace_id)
        .join(
            OrganizationMember,
            and_(
                OrganizationMember.organization_id == Workspace.organization_id,
                OrganizationMember.user_id == user_id,
            ),
        )
        .where(Document.id == document_id)
    )
    row = result.one_or_none()
    if row is None:
        raise ApplicationError(
            "Document not found",
            code="document_not_found",
            status_code=404,
        )
    return DocumentContext(document=row[0], membership=row[1])


async def resolve_conversation_context(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> ConversationContext:
    result = await session.execute(
        select(Conversation, OrganizationMember)
        .join(Workspace, Workspace.id == Conversation.workspace_id)
        .join(
            OrganizationMember,
            and_(
                OrganizationMember.organization_id == Workspace.organization_id,
                OrganizationMember.user_id == user_id,
            ),
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise ApplicationError(
            "Conversation not found",
            code="conversation_not_found",
            status_code=404,
        )
    return ConversationContext(conversation=row[0], membership=row[1])


async def resolve_evaluation_context(
    session: AsyncSession,
    run_id: UUID,
    user_id: UUID,
) -> EvaluationContext:
    result = await session.execute(
        select(EvaluationRun, OrganizationMember)
        .join(Workspace, Workspace.id == EvaluationRun.workspace_id)
        .join(
            OrganizationMember,
            and_(
                OrganizationMember.organization_id == Workspace.organization_id,
                OrganizationMember.user_id == user_id,
            ),
        )
        .where(EvaluationRun.id == run_id)
    )
    row = result.one_or_none()
    if row is None:
        raise ApplicationError(
            "Evaluation run not found",
            code="evaluation_run_not_found",
            status_code=404,
        )
    return EvaluationContext(run=row[0], membership=row[1])


def require_document_delete_role(context: DocumentContext) -> DocumentContext:
    can_delete = (
        context.document.created_by == context.membership.user_id
        or context.membership.role in {"owner", "admin"}
    )
    if not can_delete:
        raise ApplicationError(
            "Insufficient document permissions",
            code="insufficient_permissions",
            status_code=403,
        )
    return context
